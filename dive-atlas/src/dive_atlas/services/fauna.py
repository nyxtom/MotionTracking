"""Fish / animal atlas: taxa catalog, site occurrences, area guides, ID cards."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from dive_atlas.models import DiveSite, SiteSeasonality
from dive_atlas.models.fauna import SiteTaxon, Taxon

_BLOB_SPLIT = re.compile(r"[,;/]|\&|\band\b|\betc\.?", re.I)
_PARENS = re.compile(r"\(([^)]*)\)")
_NON_ALNUM = re.compile(r"[^a-z0-9\s\-/]+")


def _data_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "seeds" / "fauna_taxa.json"
        if candidate.exists():
            return parent / "data"
    if Path("data/seeds/fauna_taxa.json").exists():
        return Path("data")
    raise FileNotFoundError("fauna_taxa.json not found under data/seeds/")


def fauna_seed_path() -> Path:
    return _data_dir() / "seeds" / "fauna_taxa.json"


def load_fauna_seed(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or fauna_seed_path()
    payload = json.loads(p.read_text(encoding="utf-8"))
    return list(payload.get("taxa") or [])


def normalize_label(raw: str) -> str:
    s = (raw or "").strip().lower()
    s = s.replace("’", "'").replace("–", "-").replace("—", "-")
    s = _NON_ALNUM.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def expand_raw_labels(raw: str) -> list[str]:
    """Split PADI mega-labels into atomic tokens."""
    raw = (raw or "").strip()
    if not raw:
        return []
    labels = [raw]
    for m in _PARENS.finditer(raw):
        labels.append(m.group(1))
    out: list[str] = []
    for chunk in labels:
        # Drop the outer "Reef fish (...)" wrapper when we already expanded parens
        base = _PARENS.sub(" ", chunk).strip()
        parts = [p.strip() for p in _BLOB_SPLIT.split(base) if p.strip()]
        if not parts:
            continue
        if len(parts) == 1 and normalize_label(parts[0]) in {"reef fish", "fish", "reef fishes"}:
            continue
        out.extend(parts)
    # Always keep original for alias matching too
    out.insert(0, raw)
    # Dedupe preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        key = normalize_label(x)
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(x.strip())
    return uniq


@dataclass
class TaxonIndex:
    by_slug: dict[str, Taxon]
    by_alias: dict[str, Taxon]

    def resolve(self, raw_label: str) -> Taxon | None:
        for token in expand_raw_labels(raw_label):
            key = normalize_label(token)
            if key in self.by_alias:
                return self.by_alias[key]
            # soft singular/plural
            if key.endswith("s") and key[:-1] in self.by_alias:
                return self.by_alias[key[:-1]]
            if f"{key}s" in self.by_alias:
                return self.by_alias[f"{key}s"]
        return None


def build_taxon_index(session: Session) -> TaxonIndex:
    taxa = list(session.scalars(select(Taxon)).all())
    by_slug = {t.slug: t for t in taxa}
    by_alias: dict[str, Taxon] = {}
    for t in taxa:
        keys = {normalize_label(t.common_name), normalize_label(t.slug.replace("-", " "))}
        if t.scientific_name:
            keys.add(normalize_label(t.scientific_name))
        for a in t.aliases or []:
            keys.add(normalize_label(a))
        for k in keys:
            if k and k not in by_alias:
                by_alias[k] = t
    return TaxonIndex(by_slug=by_slug, by_alias=by_alias)


def sync_fauna_seed(session: Session, path: Path | None = None) -> dict[str, int]:
    rows = load_fauna_seed(path)
    created = updated = 0
    for row in rows:
        slug = row["slug"]
        taxon = session.scalar(select(Taxon).where(Taxon.slug == slug))
        if taxon is None:
            taxon = Taxon(slug=slug)
            session.add(taxon)
            created += 1
        else:
            updated += 1
        taxon.common_name = row["common_name"]
        taxon.scientific_name = row.get("scientific_name")
        taxon.taxon_group = row.get("taxon_group") or "fish"
        taxon.rank = row.get("rank") or "species_group"
        taxon.aliases = list(row.get("aliases") or [])
        taxon.description = row.get("description")
        taxon.id_tips = row.get("id_tips")
        taxon.size_cm_typical = row.get("size_cm_typical")
        taxon.habitat = row.get("habitat")
        taxon.danger_notes = row.get("danger_notes")
        taxon.card_worthy = bool(row.get("card_worthy", True))
        taxon.tags = list(row.get("tags") or [])
        taxon.properties = dict(row.get("properties") or {})
    session.flush()
    return {"taxa": len(rows), "created": created, "updated": updated}


def _upsert_site_taxon(
    session: Session,
    *,
    site_id: str,
    taxon: Taxon,
    source: str,
    raw_label: str,
    likelihood: float,
    seasonality_hint: str | None = None,
    seen: set[tuple[str, str, str]] | None = None,
) -> bool:
    key = (site_id, str(taxon.id), source)
    if seen is not None and key in seen:
        # Same site+taxon already queued this run (multiple alias labels)
        return False

    row = session.scalar(
        select(SiteTaxon).where(
            SiteTaxon.site_id == site_id,
            SiteTaxon.taxon_id == taxon.id,
            SiteTaxon.source == source,
        )
    )
    created = False
    if row is None:
        row = SiteTaxon(
            site_id=site_id,
            taxon_id=taxon.id,
            source=source,
            likelihood=likelihood,
            raw_label=raw_label[:300],
            evidence_count=1,
            seasonality_hint=seasonality_hint,
            properties={},
        )
        session.add(row)
        created = True
    else:
        row.evidence_count = (row.evidence_count or 1) + 1
        row.likelihood = max(float(row.likelihood or 0), likelihood)
        if seasonality_hint and not row.seasonality_hint:
            row.seasonality_hint = seasonality_hint
        if raw_label and (not row.raw_label or len(raw_label) < len(row.raw_label or "")):
            row.raw_label = raw_label[:300]
    if seen is not None:
        seen.add(key)
    return created


def mine_padi_marine_life(session: Session) -> dict[str, int]:
    """Lift dive_sites.properties.marine_life[] into taxa + site_taxa."""
    index = build_taxon_index(session)
    if not index.by_slug:
        raise RuntimeError("No taxa loaded — run fauna sync first")

    site_rows = session.execute(
        text(
            """
            SELECT id, properties->'marine_life' AS marine_life
            FROM dive_sites
            WHERE properties ? 'marine_life'
              AND jsonb_typeof(properties->'marine_life') = 'array'
              AND jsonb_array_length(properties->'marine_life') > 0
            """
        )
    ).mappings()

    linked = 0
    created = 0
    unresolved: dict[str, int] = {}
    sites_with = 0
    seen: set[tuple[str, str, str]] = set()
    for row in site_rows:
        labels = row["marine_life"] or []
        if not isinstance(labels, list) or not labels:
            continue
        sites_with += 1
        site_id = str(row["id"])
        for label in labels:
            if not isinstance(label, str) or not label.strip():
                continue
            taxon = index.resolve(label)
            if taxon is None:
                key = normalize_label(label)[:80]
                unresolved[key] = unresolved.get(key, 0) + 1
                continue
            was_new = _upsert_site_taxon(
                session,
                site_id=site_id,
                taxon=taxon,
                source="padi",
                raw_label=label,
                likelihood=0.7,
                seen=seen,
            )
            linked += 1
            if was_new:
                created += 1
        if linked % 500 == 0:
            session.flush()
    session.flush()
    top_unresolved = sorted(unresolved.items(), key=lambda kv: (-kv[1], kv[0]))[:40]
    return {
        "sites_with_labels": sites_with,
        "label_matches": linked,
        "links_created": created,
        "unresolved_labels": len(unresolved),
        "top_unresolved": top_unresolved,
    }


def mine_seasonality_highlights(session: Session) -> dict[str, int]:
    """Map site_seasonality.highlights onto taxa (e.g. mantas, whale sharks)."""
    index = build_taxon_index(session)
    rows = list(session.scalars(select(SiteSeasonality)).all())
    linked = 0
    created = 0
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        for h in row.highlights or []:
            if not isinstance(h, str) or not h.strip():
                continue
            taxon = index.resolve(h)
            if taxon is None:
                continue
            month_hint = f"month-{row.month}"
            was_new = _upsert_site_taxon(
                session,
                site_id=str(row.site_id),
                taxon=taxon,
                source="seasonality",
                raw_label=h,
                likelihood=min(0.95, 0.55 + float(row.score or 0.5) * 0.3),
                seasonality_hint=month_hint,
                seen=seen,
            )
            linked += 1
            if was_new:
                created += 1
    session.flush()
    return {
        "seasonality_rows": len(rows),
        "label_matches": linked,
        "links_created": created,
    }


@dataclass
class FaunaHit:
    taxon_slug: str
    common_name: str
    scientific_name: str | None
    taxon_group: str
    sites: int
    max_likelihood: float
    sample_localities: list[str]
    card_worthy: bool
    id_tips: str | None
    tags: list[str]


def fauna_for_area(
    session: Session,
    *,
    locality: str | None = None,
    country_code: str | None = None,
    near_lon: float | None = None,
    near_lat: float | None = None,
    radius_m: float = 50_000,
    limit: int = 40,
) -> list[FaunaHit]:
    """Aggregate taxa you might see in a locality / country / radius."""
    site_filter_sql = ["TRUE"]
    params: dict[str, Any] = {"limit": limit}
    if locality:
        site_filter_sql.append("(s.locality ILIKE :loc OR :loc_tag = ANY(s.tags))")
        params["loc"] = f"%{locality}%"
        params["loc_tag"] = locality.lower()
    if country_code:
        site_filter_sql.append("s.country_code = :cc")
        params["cc"] = country_code.upper()
    if near_lon is not None and near_lat is not None:
        site_filter_sql.append(
            """
            ST_DWithin(
              s.geom::geography,
              ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
              :radius
            )
            """
        )
        params.update({"lon": near_lon, "lat": near_lat, "radius": radius_m})

    where = " AND ".join(site_filter_sql)
    sql = text(
        f"""
        SELECT t.slug, t.common_name, t.scientific_name, t.taxon_group,
               t.card_worthy, t.id_tips, t.tags,
               COUNT(DISTINCT st.site_id) AS sites,
               MAX(st.likelihood) AS max_likelihood,
               (ARRAY_AGG(DISTINCT s.locality) FILTER (WHERE s.locality IS NOT NULL))[1:5]
                 AS localities
        FROM site_taxa st
        JOIN taxa t ON t.id = st.taxon_id
        JOIN dive_sites s ON s.id = st.site_id
        WHERE {where}
        GROUP BY t.id
        ORDER BY sites DESC, max_likelihood DESC, t.common_name
        LIMIT :limit
        """
    )
    hits: list[FaunaHit] = []
    for row in session.execute(sql, params).mappings():
        hits.append(
            FaunaHit(
                taxon_slug=row["slug"],
                common_name=row["common_name"],
                scientific_name=row["scientific_name"],
                taxon_group=row["taxon_group"],
                sites=int(row["sites"] or 0),
                max_likelihood=float(row["max_likelihood"] or 0),
                sample_localities=list(row["localities"] or []),
                card_worthy=bool(row["card_worthy"]),
                id_tips=row["id_tips"],
                tags=list(row["tags"] or []),
            )
        )
    return hits


def fauna_for_site(session: Session, *, site_id: str | None = None, site_slug: str | None = None) -> list[dict]:
    site: DiveSite | None = None
    if site_id:
        site = session.get(DiveSite, site_id)
    elif site_slug:
        site = session.scalar(select(DiveSite).where(DiveSite.slug == site_slug))
    if site is None:
        return []
    rows = session.execute(
        text(
            """
            SELECT t.slug, t.common_name, t.scientific_name, t.taxon_group,
                   t.id_tips, t.danger_notes, t.card_worthy, t.tags,
                   st.source, st.likelihood, st.raw_label, st.seasonality_hint
            FROM site_taxa st
            JOIN taxa t ON t.id = st.taxon_id
            WHERE st.site_id = :sid
            ORDER BY st.likelihood DESC, t.common_name
            """
        ),
        {"sid": str(site.id)},
    ).mappings()
    return [dict(r) for r in rows]


def export_id_cards(
    session: Session,
    *,
    locality: str | None = None,
    country_code: str | None = None,
    near_lon: float | None = None,
    near_lat: float | None = None,
    radius_m: float = 80_000,
    limit: int = 24,
    card_worthy_only: bool = True,
) -> list[dict[str, Any]]:
    """Card-deck payload for printouts: what you might see here + ID tips."""
    hits = fauna_for_area(
        session,
        locality=locality,
        country_code=country_code,
        near_lon=near_lon,
        near_lat=near_lat,
        radius_m=radius_m,
        limit=limit * 2 if card_worthy_only else limit,
    )
    cards: list[dict[str, Any]] = []
    for h in hits:
        taxon = session.scalar(select(Taxon).where(Taxon.slug == h.taxon_slug))
        if taxon is None:
            continue
        if card_worthy_only and not taxon.card_worthy:
            continue
        cards.append(
            {
                "slug": taxon.slug,
                "title": taxon.common_name,
                "scientific_name": taxon.scientific_name,
                "group": taxon.taxon_group,
                "id_tips": taxon.id_tips,
                "description": taxon.description,
                "habitat": taxon.habitat,
                "danger_notes": taxon.danger_notes,
                "size_cm_typical": taxon.size_cm_typical,
                "tags": taxon.tags,
                "likelihood": round(h.max_likelihood, 2),
                "reported_at_sites": h.sites,
                "localities": h.sample_localities,
                "area": {
                    "locality": locality,
                    "country_code": country_code,
                    "near": [near_lon, near_lat] if near_lon is not None else None,
                },
            }
        )
        if len(cards) >= limit:
            break
    return cards


def fauna_stats(session: Session) -> dict[str, int]:
    taxa = session.scalar(select(func.count()).select_from(Taxon)) or 0
    links = session.scalar(select(func.count()).select_from(SiteTaxon)) or 0
    sites = session.scalar(select(func.count(func.distinct(SiteTaxon.site_id)))) or 0
    return {"taxa": int(taxa), "site_taxon_links": int(links), "sites_with_fauna": int(sites)}
