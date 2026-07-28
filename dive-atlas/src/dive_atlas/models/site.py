from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from geoalchemy2 import Geometry
from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dive_atlas.models.base import UUID_PK, Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from dive_atlas.models.site import DiveSite
    from dive_atlas.models.source import SourceRecord


class Region(Base, TimestampMixin):
    """Hierarchical geographic container (ocean → country → coast → park…)."""

    __tablename__ = "regions"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_regions_slug"),
        Index("ix_regions_parent_id", "parent_id"),
        Index("ix_regions_country_code", "country_code"),
        Index("ix_regions_geom", "geom", postgresql_using="gist"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="custom")
    parent_id: Mapped[Optional[str]] = mapped_column(
        UUID_PK, ForeignKey("regions.id", ondelete="SET NULL"), nullable=True
    )
    country_code: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    # Approximate region footprint; sites carry precise points
    geom: Mapped[Optional[object]] = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=True)
    centroid: Mapped[Optional[object]] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    parent: Mapped[Optional[Region]] = relationship(
        remote_side="Region.id", back_populates="children"
    )
    children: Mapped[list[Region]] = relationship(back_populates="parent")
    sites: Mapped[list[DiveSite]] = relationship(back_populates="region")


class DiveSite(Base, TimestampMixin):
    """A diveable place: reef, cave, cenote, wreck, atoll pass, quarry, etc."""

    __tablename__ = "dive_sites"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_dive_sites_slug"),
        Index("ix_dive_sites_region_id", "region_id"),
        Index("ix_dive_sites_country_code", "country_code"),
        Index("ix_dive_sites_geom", "geom", postgresql_using="gist"),
        Index("ix_dive_sites_site_types", "site_types", postgresql_using="gin"),
        Index("ix_dive_sites_tags", "tags", postgresql_using="gin"),
        Index("ix_dive_sites_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(240), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    site_types: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    water_type: Mapped[str] = mapped_column(String(20), nullable=False, default="salt")
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    skill_level: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    region_id: Mapped[Optional[str]] = mapped_column(
        UUID_PK, ForeignKey("regions.id", ondelete="SET NULL"), nullable=True
    )
    country_code: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    locality: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    depth_min_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    depth_max_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    typical_visibility_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # WGS84 point (required for atlas membership). Polygon footprint optional.
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    footprint: Mapped[Optional[object]] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326), nullable=True
    )
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    # Confidence 0–1 that coordinates + identity are correct
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    region: Mapped[Optional[Region]] = relationship(back_populates="sites")
    source_records: Mapped[list[SourceRecord]] = relationship(
        back_populates="site", cascade="all, delete-orphan"
    )
    seasonality: Mapped[list[SiteSeasonality]] = relationship(
        back_populates="site", cascade="all, delete-orphan"
    )


class SiteSeasonality(Base, TimestampMixin):
    """Per-month diving conditions for a site or region-level default."""

    __tablename__ = "site_seasonality"
    __table_args__ = (
        UniqueConstraint("site_id", "month", name="uq_site_seasonality_site_month"),
        Index("ix_site_seasonality_site_id", "site_id"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    site_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="CASCADE"), nullable=False
    )
    month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–12
    # 0–1 suitability for recreational diving that month
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    water_temp_c_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    water_temp_c_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    visibility_m_typical: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    highlights: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    site: Mapped[DiveSite] = relationship(back_populates="seasonality")
