"""Corpus quality analysis + purges for non-diveable / misclassified rows."""

from __future__ import annotations

from dataclasses import dataclass, field

from slugify import slugify
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from dive_atlas.ingest.diveability import (
    TRUSTED_SITE_SOURCES,
    is_diveable_wikidata_cave,
    is_indoor_pool_name,
    is_junk_wikidata_wreck_name,
    is_operator_name,
    is_osm_non_scuba_diving_tags,
    is_osm_operator_tags,
)
from dive_atlas.models import DiveSite, Operator, SourceRecord
from dive_atlas.models.source import DataSource


@dataclass
class PurgeStats:
    candidates: int = 0
    deleted_sites: int = 0
    deleted_source_records: int = 0
    migrated_operators: int = 0
    kept_trusted: int = 0
    kept_diveable: int = 0
    sample_deleted: list[str] = field(default_factory=list)


@dataclass
class QualityBucket:
    key: str
    count: int
    severity: str  # critical | warn | info
    action: str
    samples: list[str] = field(default_factory=list)


@dataclass
class QualityReport:
    total_sites: int
    by_source: dict[str, int]
    by_type: dict[str, int]
    buckets: list[QualityBucket]

    @property
    def critical_count(self) -> int:
        return sum(b.count for b in self.buckets if b.severity == "critical")

    @property
    def warn_count(self) -> int:
        return sum(b.count for b in self.buckets if b.severity == "warn")


def _source_slugs_for_site(session: Session, site_id: str) -> set[str]:
    rows = session.execute(
        select(DataSource.slug)
        .join(SourceRecord, SourceRecord.source_id == DataSource.id)
        .where(SourceRecord.site_id == site_id)
    ).scalars().all()
    return set(rows)


def _delete_sites(session: Session, sites: list[DiveSite], stats: PurgeStats, *, dry_run: bool) -> None:
    for site in sites:
        if len(stats.sample_deleted) < 25:
            stats.sample_deleted.append(site.name)
        if dry_run:
            continue
        # Cascade delete-orphan on DiveSite.source_records removes provenance.
        n_recs = len(site.source_records or [])
        stats.deleted_source_records += n_recs
        session.delete(site)
        stats.deleted_sites += 1
    if not dry_run:
        session.flush()


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def analyze_corpus(session: Session, *, sample: int = 8) -> QualityReport:
    """Score the whole atlas for diveability / misclassification issues."""
    total = session.execute(text("SELECT COUNT(*) FROM dive_sites")).scalar() or 0

    by_source = {
        r[0]: int(r[1])
        for r in session.execute(
            text(
                """
                SELECT ds.slug, COUNT(DISTINCT s.id)
                FROM dive_sites s
                JOIN source_records sr ON sr.site_id = s.id
                JOIN data_sources ds ON ds.id = sr.source_id
                GROUP BY 1 ORDER BY 2 DESC
                """
            )
        )
    }
    by_type = {
        r[0]: int(r[1])
        for r in session.execute(
            text(
                """
                SELECT unnest(site_types) AS t, COUNT(*) AS n
                FROM dive_sites GROUP BY t ORDER BY n DESC
                """
            )
        )
    }

    buckets: list[QualityBucket] = []

    def _bucket(
        key: str,
        severity: str,
        action: str,
        ids_sql: str,
        params: dict | None = None,
    ) -> None:
        rows = session.execute(text(ids_sql), params or {}).fetchall()
        names = [r[1] for r in rows[:sample]]
        buckets.append(
            QualityBucket(
                key=key,
                count=len(rows),
                severity=severity,
                action=action,
                samples=names,
            )
        )

    _bucket(
        "wikidata_terrestrial_caves",
        "critical",
        "purge-junk-caves",
        """
        SELECT s.id::text, s.name FROM dive_sites s
        JOIN source_records sr ON sr.site_id=s.id
        JOIN data_sources ds ON ds.id=sr.source_id
        WHERE ds.slug='wikidata' AND s.site_types && ARRAY['cave']::varchar[]
          AND COALESCE(s.properties->>'wikidata_class','') = 'Q35509'
          AND COALESCE(s.properties->>'class_label','') NOT IN ('sea cave','cenote','blue hole')
          AND NOT (s.name ~* 'underwater|scuba|diving|\\mdive\\M|flooded|\\msump\\M|cenote|blue\\s+hole|sea\\s+cave|marine\\s+cave|submerged')
          AND NOT EXISTS (
            SELECT 1 FROM source_records sr2
            JOIN data_sources ds2 ON ds2.id=sr2.source_id
            WHERE sr2.site_id=s.id AND ds2.slug = ANY(:trusted)
          )
        """,
        {"trusted": list(TRUSTED_SITE_SOURCES)},
    )

    _bucket(
        "wikidata_canmore_unnamed_wrecks",
        "critical",
        "purge-junk-wrecks",
        """
        SELECT s.id::text, s.name FROM dive_sites s
        JOIN source_records sr ON sr.site_id=s.id
        JOIN data_sources ds ON ds.id=sr.source_id
        WHERE ds.slug='wikidata' AND s.site_types && ARRAY['wreck']::varchar[]
          AND (s.name ~* '^(unnamed|unknown)\\M' OR s.name ~* 'canmore'
               OR s.name ~* '\\((possibly|probably)\\)' OR s.name ~ '^Q[0-9]+$')
          AND NOT EXISTS (
            SELECT 1 FROM source_records sr2
            JOIN data_sources ds2 ON ds2.id=sr2.source_id
            WHERE sr2.site_id=s.id AND ds2.slug = ANY(:trusted)
          )
        """,
        {"trusted": list(TRUSTED_SITE_SOURCES)},
    )

    _bucket(
        "osm_dive_centres_as_sites",
        "critical",
        "purge-junk-operators (migrate→operators)",
        """
        SELECT s.id::text, s.name FROM dive_sites s
        JOIN source_records sr ON sr.site_id=s.id
        JOIN data_sources ds ON ds.id=sr.source_id
        WHERE ds.slug IN ('osm-overpass','dense-hotspots')
          AND (
            (s.properties->'osm_tags'->>'tourism') = 'dive_centre'
            OR (s.properties->'osm_tags'->>'amenity') = 'dive_centre'
            OR (s.properties->'osm_tags'->>'shop') IN ('scuba_diving','dive','diving')
            OR (s.properties->'osm_tags'->>'amenity') = 'spring_board'
          )
          AND NOT EXISTS (
            SELECT 1 FROM source_records sr2
            JOIN data_sources ds2 ON ds2.id=sr2.source_id
            WHERE sr2.site_id=s.id AND ds2.slug = 'padi-travel'
          )
        """,
    )

    _bucket(
        "qid_only_names",
        "critical",
        "purge-junk-names",
        """
        SELECT s.id::text, s.name FROM dive_sites s
        WHERE s.name ~ '^Q[0-9]+$'
          AND NOT EXISTS (
            SELECT 1 FROM source_records sr2
            JOIN data_sources ds2 ON ds2.id=sr2.source_id
            WHERE sr2.site_id=s.id AND ds2.slug = ANY(:trusted)
          )
        """,
        {"trusted": list(TRUSTED_SITE_SOURCES)},
    )

    _bucket(
        "indoor_pools",
        "critical",
        "purge-junk-pools",
        """
        SELECT id::text, name FROM dive_sites
        WHERE name ~* 'hallenbad|zwembad|indoor\\s+pool|swimming\\s+pool|piscine\\s+municipale'
        """,
    )

    _bucket(
        "wikidata_reef_geo_features",
        "warn",
        "keep as geo features (lower confidence); prefer PADI/OSM for book",
        """
        SELECT s.id::text, s.name FROM dive_sites s
        JOIN source_records sr ON sr.site_id=s.id
        JOIN data_sources ds ON ds.id=sr.source_id
        WHERE ds.slug='wikidata' AND s.site_types && ARRAY['reef']::varchar[]
          AND NOT EXISTS (
            SELECT 1 FROM source_records sr2
            JOIN data_sources ds2 ON ds2.id=sr2.source_id
            WHERE sr2.site_id=s.id AND ds2.slug = ANY(:trusted)
          )
        """,
        {"trusted": list(TRUSTED_SITE_SOURCES)},
    )

    _bucket(
        "wikidata_named_wrecks_only",
        "warn",
        "keep provisionally; many UK heritage wrecks may not be dived",
        """
        SELECT s.id::text, s.name FROM dive_sites s
        JOIN source_records sr ON sr.site_id=s.id
        JOIN data_sources ds ON ds.id=sr.source_id
        WHERE ds.slug='wikidata' AND s.site_types && ARRAY['wreck']::varchar[]
          AND NOT (s.name ~* '^(unnamed|unknown)\\M' OR s.name ~* 'canmore'
                   OR s.name ~* '\\((possibly|probably)\\)' OR s.name ~ '^Q[0-9]+$')
          AND NOT EXISTS (
            SELECT 1 FROM source_records sr2
            JOIN data_sources ds2 ON ds2.id=sr2.source_id
            WHERE sr2.site_id=s.id AND ds2.slug = ANY(:trusted)
          )
        """,
        {"trusted": list(TRUSTED_SITE_SOURCES)},
    )

    _bucket(
        "unknown_type_only",
        "warn",
        "enrich types from name/tags; operators often land here",
        """
        SELECT id::text, name FROM dive_sites
        WHERE site_types = ARRAY['unknown']::varchar[] OR site_types = '{}'::varchar[]
        """,
    )

    _bucket(
        "missing_country",
        "info",
        "enrich-geo",
        "SELECT id::text, name FROM dive_sites WHERE country_code IS NULL",
    )

    _bucket(
        "operator_like_names",
        "warn",
        "review / migrate to operators",
        """
        SELECT id::text, name FROM dive_sites
        WHERE name ~* 'dive\\s+(center|centre|shop|school|club|base)|diving\\s+(center|centre|school|club)|scuba\\s+(center|centre|shop|school|club)|centro\\s+de\\s+buceo|tauch(schule|basis)'
        """,
    )

    # Sort critical first
    order = {"critical": 0, "warn": 1, "info": 2}
    buckets.sort(key=lambda b: (order.get(b.severity, 9), -b.count, b.key))

    return QualityReport(
        total_sites=int(total),
        by_source=by_source,
        by_type=by_type,
        buckets=buckets,
    )


# ---------------------------------------------------------------------------
# Purges
# ---------------------------------------------------------------------------


def find_non_diveable_wikidata_caves(session: Session) -> list[DiveSite]:
    rows = session.execute(
        text(
            """
            SELECT DISTINCT s.id::text
            FROM dive_sites s
            JOIN source_records sr ON sr.site_id = s.id
            JOIN data_sources ds ON ds.id = sr.source_id
            WHERE ds.slug = 'wikidata'
              AND s.site_types && ARRAY['cave']::varchar[]
            """
        )
    ).scalars().all()
    out: list[DiveSite] = []
    for site_id in rows:
        site = session.get(DiveSite, site_id)
        if site is None:
            continue
        slugs = _source_slugs_for_site(session, site_id)
        if slugs & TRUSTED_SITE_SOURCES:
            continue
        props = site.properties or {}
        if is_diveable_wikidata_cave(
            name=site.name,
            class_qid=props.get("wikidata_class"),
            class_label=props.get("class_label"),
        ):
            continue
        if "sea_cave" in (site.tags or []):
            continue
        out.append(site)
    return out


def purge_non_diveable_wikidata_caves(
    session: Session, *, dry_run: bool = False, sample: int = 25
) -> PurgeStats:
    stats = PurgeStats()
    wikidata_caves = session.execute(
        text(
            """
            SELECT COUNT(DISTINCT s.id)
            FROM dive_sites s
            JOIN source_records sr ON sr.site_id = s.id
            JOIN data_sources ds ON ds.id = sr.source_id
            WHERE ds.slug = 'wikidata'
              AND s.site_types && ARRAY['cave']::varchar[]
            """
        )
    ).scalar() or 0
    victims = find_non_diveable_wikidata_caves(session)
    stats.candidates = len(victims)
    stats.kept_diveable = max(0, wikidata_caves - len(victims))
    _delete_sites(session, victims, stats, dry_run=dry_run)
    return stats


def find_junk_wikidata_wrecks(session: Session) -> list[DiveSite]:
    rows = session.execute(
        text(
            """
            SELECT DISTINCT s.id::text
            FROM dive_sites s
            JOIN source_records sr ON sr.site_id = s.id
            JOIN data_sources ds ON ds.id = sr.source_id
            WHERE ds.slug = 'wikidata'
              AND s.site_types && ARRAY['wreck']::varchar[]
            """
        )
    ).scalars().all()
    out: list[DiveSite] = []
    for site_id in rows:
        site = session.get(DiveSite, site_id)
        if site is None:
            continue
        if _source_slugs_for_site(session, site_id) & TRUSTED_SITE_SOURCES:
            continue
        if is_junk_wikidata_wreck_name(site.name):
            out.append(site)
    return out


def purge_junk_wikidata_wrecks(session: Session, *, dry_run: bool = False) -> PurgeStats:
    stats = PurgeStats()
    victims = find_junk_wikidata_wrecks(session)
    stats.candidates = len(victims)
    _delete_sites(session, victims, stats, dry_run=dry_run)
    return stats


def find_qid_only_sites(session: Session) -> list[DiveSite]:
    rows = session.execute(
        text(
            """
            SELECT id::text FROM dive_sites WHERE name ~ '^Q[0-9]+$'
            """
        )
    ).scalars().all()
    out: list[DiveSite] = []
    for site_id in rows:
        site = session.get(DiveSite, site_id)
        if site is None:
            continue
        if _source_slugs_for_site(session, site_id) & TRUSTED_SITE_SOURCES:
            continue
        out.append(site)
    return out


def purge_qid_only_names(session: Session, *, dry_run: bool = False) -> PurgeStats:
    stats = PurgeStats()
    victims = find_qid_only_sites(session)
    stats.candidates = len(victims)
    _delete_sites(session, victims, stats, dry_run=dry_run)
    return stats


def find_indoor_pools(session: Session) -> list[DiveSite]:
    rows = session.execute(text("SELECT id::text, name FROM dive_sites")).fetchall()
    out: list[DiveSite] = []
    for site_id, name in rows:
        if is_indoor_pool_name(name):
            # Keep Caribbean "La Piscine" style named dive sites if PADI/seed
            site = session.get(DiveSite, site_id)
            if site is None:
                continue
            slugs = _source_slugs_for_site(session, site_id)
            if "padi-travel" in slugs or any(s.startswith("seed-") for s in slugs):
                # Still drop obvious indoor pools
                if name and any(
                    k in name.lower()
                    for k in ("hallenbad", "zwembad", "indoor pool", "swimming pool")
                ):
                    out.append(site)
                continue
            out.append(site)
    return out


def purge_indoor_pools(session: Session, *, dry_run: bool = False) -> PurgeStats:
    stats = PurgeStats()
    victims = find_indoor_pools(session)
    stats.candidates = len(victims)
    _delete_sites(session, victims, stats, dry_run=dry_run)
    return stats


def find_osm_operator_sites(session: Session) -> list[DiveSite]:
    rows = session.execute(
        text(
            """
            SELECT DISTINCT s.id::text
            FROM dive_sites s
            JOIN source_records sr ON sr.site_id = s.id
            JOIN data_sources ds ON ds.id = sr.source_id
            WHERE ds.slug IN ('osm-overpass', 'dense-hotspots')
            """
        )
    ).scalars().all()
    out: list[DiveSite] = []
    for site_id in rows:
        site = session.get(DiveSite, site_id)
        if site is None:
            continue
        slugs = _source_slugs_for_site(session, site_id)
        if "padi-travel" in slugs or any(s.startswith("seed-") for s in slugs):
            continue
        tags = (site.properties or {}).get("osm_tags") or {}
        if is_osm_operator_tags(tags) or is_osm_non_scuba_diving_tags(tags):
            out.append(site)
            continue
        if is_operator_name(site.name) and (
            site.site_types == ["unknown"] or not site.site_types
        ):
            out.append(site)
    return out


def migrate_osm_operators(
    session: Session, *, dry_run: bool = False
) -> PurgeStats:
    """Move OSM dive centres out of dive_sites into operators."""
    stats = PurgeStats()
    victims = find_osm_operator_sites(session)
    stats.candidates = len(victims)
    for site in victims:
        if len(stats.sample_deleted) < 25:
            stats.sample_deleted.append(site.name)
        if dry_run:
            continue
        tags = (site.properties or {}).get("osm_tags") or {}
        slug = f"op-{slugify(site.slug or site.name)}"[:240]
        existing = session.execute(select(Operator).where(Operator.slug == slug)).scalar_one_or_none()
        if existing is None:
            op = Operator(
                slug=slug,
                name=site.name,
                kind="dive_shop",
                country_code=site.country_code,
                locality=site.locality,
                website=tags.get("website") or tags.get("contact:website"),
                phone=tags.get("phone") or tags.get("contact:phone"),
                geom=site.geom,
                tags=["migrated_from_site", "osm"],
                properties={
                    "from_site_id": str(site.id),
                    "osm_tags": tags,
                    "external_url": next(
                        (
                            r.external_url
                            for r in (site.source_records or [])
                            if r.external_url
                        ),
                        None,
                    ),
                },
            )
            session.add(op)
            stats.migrated_operators += 1
        n_recs = len(site.source_records or [])
        stats.deleted_source_records += n_recs
        session.delete(site)
        stats.deleted_sites += 1
    if not dry_run:
        session.flush()
    return stats


def purge_all_junk(session: Session, *, dry_run: bool = False) -> dict[str, PurgeStats]:
    """Run every critical purge in a safe order."""
    return {
        "caves": purge_non_diveable_wikidata_caves(session, dry_run=dry_run),
        "wrecks": purge_junk_wikidata_wrecks(session, dry_run=dry_run),
        "operators": migrate_osm_operators(session, dry_run=dry_run),
        "qid_names": purge_qid_only_names(session, dry_run=dry_run),
        "pools": purge_indoor_pools(session, dry_run=dry_run),
    }


def demote_wikidata_reef_confidence(session: Session, *, confidence: float = 0.45) -> int:
    """Mark Wikidata-only reefs as provisional geo features (not curated dive sites)."""
    result = session.execute(
        text(
            """
            UPDATE dive_sites s
            SET confidence = LEAST(s.confidence, :conf),
                tags = CASE
                  WHEN 'geo_feature' = ANY(s.tags) THEN s.tags
                  ELSE array_append(s.tags, 'geo_feature')
                END,
                properties = s.properties || jsonb_build_object('quality_note', 'wikidata_reef_geo_feature')
            WHERE EXISTS (
              SELECT 1 FROM source_records sr
              JOIN data_sources ds ON ds.id = sr.source_id
              WHERE sr.site_id = s.id AND ds.slug = 'wikidata'
            )
            AND s.site_types && ARRAY['reef']::varchar[]
            AND NOT EXISTS (
              SELECT 1 FROM source_records sr2
              JOIN data_sources ds2 ON ds2.id = sr2.source_id
              WHERE sr2.site_id = s.id AND ds2.slug = ANY(:trusted)
            )
            """
        ),
        {"conf": confidence, "trusted": list(TRUSTED_SITE_SOURCES)},
    )
    session.flush()
    return result.rowcount or 0
