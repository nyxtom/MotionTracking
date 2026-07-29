from __future__ import annotations

from typing import Optional

from geoalchemy2 import Geography
from geoalchemy2.functions import ST_DWithin, ST_MakePoint, ST_SetSRID, ST_X, ST_Y
from sqlalchemy import Select, cast, or_, select
from sqlalchemy.orm import Session

from dive_atlas.models import DiveSite
from dive_atlas.schemas import DiveSiteOut


def _to_out(row: DiveSite, lon: float, lat: float) -> DiveSiteOut:
    return DiveSiteOut(
        id=row.id,
        slug=row.slug,
        name=row.name,
        site_types=list(row.site_types or []),
        country_code=row.country_code,
        locality=row.locality,
        lon=lon,
        lat=lat,
        depth_min_m=row.depth_min_m,
        depth_max_m=row.depth_max_m,
        skill_level=row.skill_level,
        diveable=bool(getattr(row, "diveable", True)),
        access=getattr(row, "access", None) or "recreational",
        confidence=row.confidence,
        tags=list(row.tags or []),
    )


def search_sites(
    session: Session,
    *,
    q: Optional[str] = None,
    site_type: Optional[str] = None,
    country_code: Optional[str] = None,
    near_lon: Optional[float] = None,
    near_lat: Optional[float] = None,
    radius_m: float = 50_000,
    diveable: Optional[bool] = None,
    access: Optional[str] = None,
    limit: int = 50,
) -> list[DiveSiteOut]:
    lon_col = ST_X(DiveSite.geom)
    lat_col = ST_Y(DiveSite.geom)
    stmt: Select = select(DiveSite, lon_col, lat_col)

    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                DiveSite.name.ilike(pattern),
                DiveSite.locality.ilike(pattern),
                DiveSite.slug.ilike(pattern),
            )
        )
    if site_type:
        stmt = stmt.where(DiveSite.site_types.any(site_type))
    if country_code:
        stmt = stmt.where(DiveSite.country_code == country_code.upper())
    if diveable is not None:
        stmt = stmt.where(DiveSite.diveable.is_(diveable))
    if access:
        stmt = stmt.where(DiveSite.access == access)
    if near_lon is not None and near_lat is not None:
        point = ST_SetSRID(ST_MakePoint(near_lon, near_lat), 4326)
        stmt = stmt.where(
            ST_DWithin(
                cast(DiveSite.geom, Geography),
                cast(point, Geography),
                radius_m,
            )
        )

    stmt = stmt.order_by(DiveSite.name).limit(limit)
    rows = session.execute(stmt).all()
    return [_to_out(site, float(lon), float(lat)) for site, lon, lat in rows]
