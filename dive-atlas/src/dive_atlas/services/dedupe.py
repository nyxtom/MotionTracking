"""Near-duplicate dive site merge.

PADI / OSM / seed often emit the same reef as separate rows (different slugs).
Cluster by normalized name + distance, keep a survivor, re-point provenance.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from dive_atlas.models import DiveSite, SiteSeasonality, SourceRecord
from dive_atlas.models.fauna import SiteTaxon


@dataclass
class DedupeStats:
    pairs: int = 0
    clusters: int = 0
    merged: int = 0
    survivors: int = 0


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        self.parent.setdefault(x, x)

    def find(self, x: str) -> str:
        self.add(x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def find_duplicate_pairs(
    session: Session, *, max_distance_m: float = 150.0, limit: int | None = None
) -> list[tuple[str, str, float]]:
    """Return (id_a, id_b, meters) pairs with same name-key within distance."""
    sql = text(
        """
        WITH pts AS (
          SELECT id,
                 lower(regexp_replace(
                   regexp_replace(name, '(?i)dive\\s*site|divesite|scuba|diving', '', 'g'),
                   '[^a-zA-Z0-9]+', '', 'g'
                 )) AS nkey,
                 geom::geography AS g
          FROM dive_sites
          WHERE geom IS NOT NULL
        )
        SELECT a.id::text, b.id::text, ST_Distance(a.g, b.g) AS meters
        FROM pts a
        JOIN pts b
          ON a.id < b.id
         AND a.nkey = b.nkey
         AND length(a.nkey) >= 4
         AND ST_DWithin(a.g, b.g, :dist)
        ORDER BY meters, a.id, b.id
        """
        + (" LIMIT :lim" if limit else "")
    )
    params: dict = {"dist": max_distance_m}
    if limit:
        params["lim"] = limit
    return [(r[0], r[1], float(r[2])) for r in session.execute(sql, params).all()]


def _survivor_score(site: DiveSite) -> tuple:
    tags = {t.lower() for t in (site.tags or [])}
    prefer = 0
    if "seed" in tags or any(t.startswith("seed") for t in tags):
        prefer += 3
    if "padi" in tags or "padi-travel" in tags:
        prefer += 2
    if site.properties and site.properties.get("marine_life"):
        prefer += 2
    if site.description:
        prefer += 1
    if site.locality:
        prefer += 1
    if site.country_code:
        prefer += 1
    ml_n = len(site.properties.get("marine_life") or []) if site.properties else 0
    return (prefer, float(site.confidence or 0), ml_n, len(site.tags or []))


def _merge_site_fields(survivor: DiveSite, loser: DiveSite) -> None:
    # Prefer non-null / richer fields on survivor
    if not survivor.country_code and loser.country_code:
        survivor.country_code = loser.country_code
    if (not survivor.locality or len(survivor.locality) < 3) and loser.locality:
        # Prefer more specific locality (longer / not vague tile name)
        survivor.locality = loser.locality
    elif loser.locality and survivor.locality:
        vague = {"indonesia_east", "indonesia_west", "yucatan_carib", "florida", "caribbean"}
        if survivor.locality.lower() in vague and loser.locality.lower() not in vague:
            survivor.locality = loser.locality
    if not survivor.description and loser.description:
        survivor.description = loser.description
    if survivor.depth_min_m is None and loser.depth_min_m is not None:
        survivor.depth_min_m = loser.depth_min_m
    if survivor.depth_max_m is None and loser.depth_max_m is not None:
        survivor.depth_max_m = loser.depth_max_m
    elif loser.depth_max_m is not None and survivor.depth_max_m is not None:
        survivor.depth_max_m = max(survivor.depth_max_m, loser.depth_max_m)

    aliases = list(survivor.aliases or [])
    for a in [loser.name, *(loser.aliases or []), loser.slug]:
        if a and a not in aliases and a != survivor.name:
            aliases.append(a)
    survivor.aliases = aliases

    tags = list(dict.fromkeys([*(survivor.tags or []), *(loser.tags or []), "deduped"]))
    survivor.tags = tags

    types = list(dict.fromkeys([*(survivor.site_types or []), *(loser.site_types or [])]))
    survivor.site_types = types

    props = {**(loser.properties or {}), **(survivor.properties or {})}
    # Union marine_life lists
    ml = []
    seen = set()
    for src in (survivor.properties or {}, loser.properties or {}):
        for label in src.get("marine_life") or []:
            if not isinstance(label, str):
                continue
            key = label.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            ml.append(label.strip())
    if ml:
        props["marine_life"] = ml
    props.setdefault("merged_slugs", [])
    merged = list(props.get("merged_slugs") or [])
    if loser.slug and loser.slug not in merged:
        merged.append(loser.slug)
    props["merged_slugs"] = merged
    survivor.properties = props
    survivor.confidence = max(float(survivor.confidence or 0), float(loser.confidence or 0))


def _repoint_source_records(session: Session, survivor_id: str, loser_id: str) -> None:
    session.execute(
        update(SourceRecord)
        .where(SourceRecord.site_id == loser_id)
        .values(site_id=survivor_id)
    )


def _merge_site_taxa(session: Session, survivor_id: str, loser_id: str) -> None:
    loser_rows = list(
        session.scalars(select(SiteTaxon).where(SiteTaxon.site_id == loser_id)).all()
    )
    for row in loser_rows:
        existing = session.scalar(
            select(SiteTaxon).where(
                SiteTaxon.site_id == survivor_id,
                SiteTaxon.taxon_id == row.taxon_id,
                SiteTaxon.source == row.source,
            )
        )
        if existing:
            existing.evidence_count = (existing.evidence_count or 1) + (row.evidence_count or 1)
            existing.likelihood = max(float(existing.likelihood or 0), float(row.likelihood or 0))
            if row.seasonality_hint and not existing.seasonality_hint:
                existing.seasonality_hint = row.seasonality_hint
            session.delete(row)
        else:
            row.site_id = survivor_id


def _merge_seasonality(session: Session, survivor_id: str, loser_id: str) -> None:
    loser_rows = list(
        session.scalars(select(SiteSeasonality).where(SiteSeasonality.site_id == loser_id)).all()
    )
    for row in loser_rows:
        existing = session.scalar(
            select(SiteSeasonality).where(
                SiteSeasonality.site_id == survivor_id,
                SiteSeasonality.month == row.month,
            )
        )
        if existing:
            existing.score = max(float(existing.score or 0), float(row.score or 0))
            hl = list(dict.fromkeys([*(existing.highlights or []), *(row.highlights or [])]))
            existing.highlights = hl
            session.delete(row)
        else:
            row.site_id = survivor_id


def _drop_unique_child(session: Session, table: str, survivor_id: str, loser_id: str) -> None:
    """For 1:1 tables — keep survivor row, delete loser row."""
    session.execute(
        text(f"DELETE FROM {table} WHERE site_id = :l"),
        {"l": loser_id},
    )


def _repoint_or_drop_unique(
    session: Session, table: str, survivor_id: str, loser_id: str, unique_cols: list[str]
) -> None:
    """Repoint rows; on unique conflict, drop the loser row."""
    if not unique_cols:
        session.execute(
            text(f"UPDATE {table} SET site_id = :s WHERE site_id = :l"),
            {"s": survivor_id, "l": loser_id},
        )
        return
    # Delete loser rows that would collide, then repoint the rest
    cols = ", ".join(unique_cols)
    session.execute(
        text(
            f"""
            DELETE FROM {table} l
            USING {table} s
            WHERE l.site_id = :l AND s.site_id = :s
              AND ({' AND '.join(f'l.{c} = s.{c}' for c in unique_cols)})
            """
        ),
        {"s": survivor_id, "l": loser_id},
    )
    session.execute(
        text(f"UPDATE {table} SET site_id = :s WHERE site_id = :l"),
        {"s": survivor_id, "l": loser_id},
    )


def merge_cluster(session: Session, site_ids: list[str]) -> str:
    sites = list(session.scalars(select(DiveSite).where(DiveSite.id.in_(site_ids))).all())
    if len(sites) < 2:
        return site_ids[0]
    sites.sort(key=_survivor_score, reverse=True)
    survivor = sites[0]
    for loser in sites[1:]:
        _merge_site_fields(survivor, loser)
        _repoint_source_records(session, str(survivor.id), str(loser.id))
        _merge_site_taxa(session, str(survivor.id), str(loser.id))
        _merge_seasonality(session, str(survivor.id), str(loser.id))
        for table in ("site_profiles", "site_briefings", "site_encyclopedia"):
            _drop_unique_child(session, table, str(survivor.id), str(loser.id))
        _repoint_or_drop_unique(
            session, "site_operator_links", str(survivor.id), str(loser.id), ["operator_id"]
        )
        for table in (
            "dive_route_stops",
            "eco_events",
            "incidents",
            "phenomenon_occurrences",
            "sightings",
            "survey_assets",
        ):
            session.execute(
                text(f"UPDATE {table} SET site_id = :s WHERE site_id = :l"),
                {"s": str(survivor.id), "l": str(loser.id)},
            )
        session.flush()
        session.delete(loser)
    session.flush()
    return str(survivor.id)


def dedupe_sites(
    session: Session,
    *,
    max_distance_m: float = 150.0,
    dry_run: bool = False,
    limit_pairs: int | None = None,
) -> dict:
    pairs = find_duplicate_pairs(session, max_distance_m=max_distance_m, limit=limit_pairs)
    uf = _UnionFind()
    for a, b, _ in pairs:
        uf.union(a, b)
    clusters: dict[str, list[str]] = defaultdict(list)
    for a, b, _ in pairs:
        root = uf.find(a)
        clusters[root].append(a)
        clusters[root].append(b)
    # unique members per cluster
    cluster_list = []
    for members in clusters.values():
        uniq = sorted(set(members))
        if len(uniq) >= 2:
            cluster_list.append(uniq)

    stats = DedupeStats(pairs=len(pairs), clusters=len(cluster_list))
    if dry_run:
        return {
            "pairs": stats.pairs,
            "clusters": stats.clusters,
            "merged": 0,
            "survivors": 0,
            "dry_run": True,
            "sample_clusters": cluster_list[:10],
        }

    for members in cluster_list:
        merge_cluster(session, members)
        stats.merged += len(members) - 1
        stats.survivors += 1
    session.flush()
    return {
        "pairs": stats.pairs,
        "clusters": stats.clusters,
        "merged": stats.merged,
        "survivors": stats.survivors,
        "dry_run": False,
    }
