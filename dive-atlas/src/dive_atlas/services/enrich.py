"""GIS helpers for post-atlas operator enrichment.

Shops/operators are not required to build the atlas. Once sites exist, run
proximity joins (ST_DWithin) against Places/OSM dive-shop points.
"""

from __future__ import annotations

from geoalchemy2 import Geography
from geoalchemy2.functions import ST_DWithin, ST_Distance
from sqlalchemy import cast, select
from sqlalchemy.orm import Session

from dive_atlas.config import get_settings
from dive_atlas.models import DiveSite, Operator, SiteOperatorLink


def link_nearby_operators(
    session: Session,
    *,
    radius_m: int | None = None,
    relation: str = "nearby",
) -> int:
    """Create SiteOperatorLink rows for operators within radius of each site.

    Idempotent on (site_id, operator_id). Returns number of new links.
    """
    radius = radius_m if radius_m is not None else get_settings().operator_enrichment_radius_m
    sites = session.scalars(select(DiveSite).where(DiveSite.geom.is_not(None))).all()
    operators = session.scalars(select(Operator).where(Operator.geom.is_not(None))).all()
    created = 0
    for site in sites:
        for op in operators:
            # Distance filter in SQL would be preferable at scale; fine for early atlas.
            within = session.scalar(
                select(
                    ST_DWithin(
                        cast(site.geom, Geography),
                        cast(op.geom, Geography),
                        radius,
                    )
                )
            )
            if not within:
                continue
            existing = session.scalar(
                select(SiteOperatorLink).where(
                    SiteOperatorLink.site_id == site.id,
                    SiteOperatorLink.operator_id == op.id,
                )
            )
            if existing:
                continue
            dist = session.scalar(
                select(
                    ST_Distance(
                        cast(site.geom, Geography),
                        cast(op.geom, Geography),
                    )
                )
            )
            session.add(
                SiteOperatorLink(
                    site_id=site.id,
                    operator_id=op.id,
                    relation=relation,
                    distance_m=float(dist) if dist is not None else None,
                    confidence=0.5,
                )
            )
            created += 1
    return created
