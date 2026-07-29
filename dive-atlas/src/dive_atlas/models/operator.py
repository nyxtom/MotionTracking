"""Operator / shop stubs for later GIS enrichment.

Shops are intentionally separate from dive sites. After the atlas has site
points, enrich with ST_DWithin against Google Places (or similar) rather than
limiting the atlas to bookable PADI inventory.
"""

from __future__ import annotations

from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dive_atlas.models.base import UUID_PK, Base, TimestampMixin, new_uuid


class Operator(Base, TimestampMixin):
    __tablename__ = "operators"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_operators_slug"),
        Index("ix_operators_geom", "geom", postgresql_using="gist"),
        Index("ix_operators_country_code", "country_code"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(240), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="dive_shop")
    # dive_shop | liveaboard | resort | charter | freedive | unknown
    country_code: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    locality: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    geom: Mapped[Optional[object]] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class SiteOperatorLink(Base, TimestampMixin):
    """Many-to-many produced by GIS proximity and/or explicit claims."""

    __tablename__ = "site_operator_links"
    __table_args__ = (
        UniqueConstraint("site_id", "operator_id", name="uq_site_operator"),
        Index("ix_site_operator_links_site_id", "site_id"),
        Index("ix_site_operator_links_operator_id", "operator_id"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    site_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="CASCADE"), nullable=False
    )
    operator_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(40), nullable=False, default="nearby")
    # nearby | services | exclusive | claimed
    distance_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.4)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
