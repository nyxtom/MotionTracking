"""Quality filters: remove open-data junk that is not actually diveable."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from dive_atlas.ingest.diveability import (
    TRUSTED_CAVE_SOURCES,
    is_diveable_wikidata_cave,
)
from dive_atlas.models import DiveSite, SourceRecord
from dive_atlas.models.source import DataSource


@dataclass
class PurgeStats:
    candidates: int = 0
    deleted_sites: int = 0
    deleted_source_records: int = 0
    kept_trusted: int = 0
    kept_diveable: int = 0
    sample_deleted: list[str] = field(default_factory=list)


def _source_slugs_for_site(session: Session, site_id: str) -> set[str]:
    rows = session.execute(
        select(DataSource.slug)
        .join(SourceRecord, SourceRecord.source_id == DataSource.id)
        .where(SourceRecord.site_id == site_id)
    ).scalars().all()
    return set(rows)


def find_non_diveable_wikidata_caves(session: Session) -> list[DiveSite]:
    """Wikidata-sourced caves that look terrestrial / archaeological, not diveable.

    Keeps sites that also have a trusted (PADI / OSM / seed / dense) source, or
    whose Wikidata class / name passes the diveability gate.
    """
    # Prefer caves that have *any* wikidata provenance and cave typing.
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
        if slugs & TRUSTED_CAVE_SOURCES:
            continue
        # Only Wikidata (and maybe stubs) — judge by class + name.
        props = site.properties or {}
        if is_diveable_wikidata_cave(
            name=site.name,
            class_qid=props.get("wikidata_class"),
            class_label=props.get("class_label"),
        ):
            continue
        # Also keep if tags already mark sea_cave from a prior good ingest.
        if "sea_cave" in (site.tags or []):
            continue
        out.append(site)
    return out


def purge_non_diveable_wikidata_caves(
    session: Session, *, dry_run: bool = False, sample: int = 25
) -> PurgeStats:
    """Delete Wikidata-only terrestrial caves from the atlas."""
    stats = PurgeStats()
    # Count kept for reporting
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

    for site in victims:
        if len(stats.sample_deleted) < sample:
            stats.sample_deleted.append(site.name)
        if dry_run:
            continue
        # SourceRecord.site_id is ON DELETE SET NULL — remove provenance rows first.
        res = session.execute(delete(SourceRecord).where(SourceRecord.site_id == site.id))
        stats.deleted_source_records += res.rowcount or 0
        session.delete(site)
        stats.deleted_sites += 1

    if not dry_run:
        session.flush()
    return stats
