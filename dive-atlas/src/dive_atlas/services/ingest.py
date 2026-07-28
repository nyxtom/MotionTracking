from __future__ import annotations

from geoalchemy2 import WKTElement
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from dive_atlas.ingest.base import IngestBatch
from dive_atlas.models import DataSource, DiveSite, Region, SiteSeasonality, SourceRecord
from dive_atlas.schemas import DiveSiteIn, RegionIn


def _point(lon: float, lat: float) -> WKTElement:
    return WKTElement(f"POINT({lon} {lat})", srid=4326)


def ensure_source(session: Session, batch: IngestBatch) -> DataSource:
    source = session.scalar(select(DataSource).where(DataSource.slug == batch.source_slug))
    if source is None:
        source = DataSource(
            slug=batch.source_slug,
            name=batch.source_name,
            kind=batch.source_kind.value,
            properties=batch.meta or {},
        )
        session.add(source)
        session.flush()
    return source


def upsert_region(session: Session, payload: RegionIn, cache: dict[str, Region]) -> Region:
    if payload.slug in cache:
        return cache[payload.slug]
    region = session.scalar(select(Region).where(Region.slug == payload.slug))
    parent_id = None
    if payload.parent_slug:
        parent = cache.get(payload.parent_slug) or session.scalar(
            select(Region).where(Region.slug == payload.parent_slug)
        )
        if parent is None:
            raise ValueError(f"Parent region {payload.parent_slug!r} not found for {payload.slug}")
        parent_id = parent.id
        cache[parent.slug] = parent

    if region is None:
        region = Region(slug=payload.slug, aliases=[], properties={})
        session.add(region)

    region.name = payload.name
    region.kind = payload.kind
    region.parent_id = parent_id
    region.country_code = payload.country_code
    region.description = payload.description
    region.aliases = payload.aliases
    region.properties = payload.properties or {}
    session.flush()
    cache[region.slug] = region
    return region


def upsert_site(
    session: Session,
    source: DataSource,
    payload: DiveSiteIn,
    region_cache: dict[str, Region],
) -> DiveSite:
    slug = payload.slug or slugify(f"{payload.country_code or 'xx'}-{payload.name}")
    site = session.scalar(select(DiveSite).where(DiveSite.slug == slug))
    region_id = None
    if payload.region_slug:
        region = region_cache.get(payload.region_slug) or session.scalar(
            select(Region).where(Region.slug == payload.region_slug)
        )
        if region is None:
            raise ValueError(f"Region {payload.region_slug!r} missing for site {payload.name}")
        region_id = region.id
        region_cache[region.slug] = region

    if site is None:
        site = DiveSite(
            slug=slug,
            geom=_point(payload.lon, payload.lat),
            aliases=[],
            site_types=[],
            tags=[],
            properties={},
            confidence=payload.confidence,
        )
        session.add(site)
    else:
        # Only overwrite coordinates when incoming confidence is higher
        if payload.confidence >= (site.confidence or 0):
            site.geom = _point(payload.lon, payload.lat)
            site.confidence = payload.confidence

    site.name = payload.name
    site.aliases = payload.aliases
    site.site_types = payload.site_types
    site.water_type = payload.water_type
    site.entry_type = payload.entry_type
    site.skill_level = payload.skill_level
    site.region_id = region_id
    # Prefer non-null geo fields; keep richer locality over vague tile hints
    if payload.country_code:
        site.country_code = payload.country_code
    if payload.locality:
        site.locality = payload.locality
    site.description = payload.description
    site.depth_min_m = payload.depth_min_m
    site.depth_max_m = payload.depth_max_m
    site.typical_visibility_m = payload.typical_visibility_m
    # Merge tags rather than replace
    merged_tags = list(dict.fromkeys([*(site.tags or []), *(payload.tags or [])]))
    site.tags = merged_tags
    site.properties = {**(site.properties or {}), **payload.properties}
    session.flush()

    for season in payload.seasonality:
        row = session.scalar(
            select(SiteSeasonality).where(
                SiteSeasonality.site_id == site.id,
                SiteSeasonality.month == season.month,
            )
        )
        if row is None:
            row = SiteSeasonality(
                site_id=site.id,
                month=season.month,
                highlights=[],
                properties={},
            )
            session.add(row)
        row.score = season.score
        row.water_temp_c_min = season.water_temp_c_min
        row.water_temp_c_max = season.water_temp_c_max
        row.visibility_m_typical = season.visibility_m_typical
        row.notes = season.notes
        row.highlights = season.highlights

    external_id = payload.external_id or slug
    record = session.scalar(
        select(SourceRecord).where(
            SourceRecord.source_id == source.id,
            SourceRecord.external_id == external_id,
        )
    )
    if record is None:
        record = SourceRecord(
            source_id=source.id,
            external_id=external_id,
            raw={},
        )
        session.add(record)
    record.site_id = site.id
    record.external_url = payload.external_url
    record.title = payload.name
    record.raw = payload.raw or payload.model_dump()
    record.confidence = payload.confidence
    session.flush()
    return site


def ingest_batch(session: Session, batch: IngestBatch) -> dict[str, int]:
    source = ensure_source(session, batch)
    region_cache: dict[str, Region] = {}
    # Parents first: stable if seed lists parents before children
    for region in batch.regions:
        upsert_region(session, region, region_cache)
    site_count = 0
    for site in batch.sites:
        upsert_site(session, source, site, region_cache)
        site_count += 1
    return {"regions": len(batch.regions), "sites": site_count}
