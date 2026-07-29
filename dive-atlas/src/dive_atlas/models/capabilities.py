"""Capability layers on top of dive_sites.

Trip design · safety · science · content · routes · AR/VR survey assets.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dive_atlas.models.base import UUID_PK, Base, TimestampMixin, new_uuid


class SiteProfile(Base, TimestampMixin):
    """Skill gates + operational profile for a site (1:1 with dive_sites)."""

    __tablename__ = "site_profiles"
    __table_args__ = (
        UniqueConstraint("site_id", name="uq_site_profiles_site"),
        Index("ix_site_profiles_overhead", "overhead_class"),
        Index("ix_site_profiles_certs", "cert_required", postgresql_using="gin"),
        Index("ix_site_profiles_experiences", "experiences", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    site_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="CASCADE"), nullable=False
    )
    cert_required: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    # e.g. ["aow", "nitrox"] — ALL required unless notes say otherwise
    cert_recommended: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    overhead_class: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    deco_likely: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_depth_advisory_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_class: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    gas_mixes: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    surface_support_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    beginner_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    experiences: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    # caves | pelagics | macro | wreck | wall | drift | night | ...
    monsoon_months: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    best_months: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class SiteBriefing(Base, TimestampMixin):
    """Living site briefing — safety & ops copy linked to a site."""

    __tablename__ = "site_briefings"
    __table_args__ = (
        UniqueConstraint("site_id", name="uq_site_briefings_site"),
        Index("ix_site_briefings_hazards", "hazards", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    site_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="CASCADE"), nullable=False
    )
    entry_exit: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    currents: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thermoclines: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    overhead_rules: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hazards: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    hazard_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deco_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    nearest_chamber: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    nearest_chamber_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    local_regs: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    marine_park_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    emergency_contacts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class Phenomenon(Base, TimestampMixin):
    """Recurring natural phenomenon template (manta season, sardine run…)."""

    __tablename__ = "phenomena"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_phenomena_slug"),
        Index("ix_phenomena_type", "phenomenon_type"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    phenomenon_type: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    typical_months: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    region_slug: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class PhenomenonOccurrence(Base, TimestampMixin):
    """Timed occurrence of a phenomenon at a site or region (calendar row)."""

    __tablename__ = "phenomenon_occurrences"
    __table_args__ = (
        Index("ix_phenomenon_occurrences_phenomenon_id", "phenomenon_id"),
        Index("ix_phenomenon_occurrences_site_id", "site_id"),
        Index("ix_phenomenon_occurrences_window", "window_start", "window_end"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    phenomenon_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("phenomena.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[Optional[str]] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="SET NULL"), nullable=True
    )
    region_id: Mapped[Optional[str]] = mapped_column(
        UUID_PK, ForeignKey("regions.id", ondelete="SET NULL"), nullable=True
    )
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    window_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    window_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    peak_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    peak_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class DiveRoute(Base, TimestampMixin):
    """Narrative / curated route: cenote spine, Ring of Fire wrecks, atoll chain…"""

    __tablename__ = "dive_routes"
    __table_args__ = (UniqueConstraint("slug", name="uq_dive_routes_slug"),)

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="custom")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    estimated_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cert_required: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    geom: Mapped[Optional[object]] = mapped_column(Geometry("LINESTRING", srid=4326), nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class DiveRouteStop(Base, TimestampMixin):
    __tablename__ = "dive_route_stops"
    __table_args__ = (
        UniqueConstraint("route_id", "position", name="uq_dive_route_stops_pos"),
        Index("ix_dive_route_stops_route_id", "route_id"),
        Index("ix_dive_route_stops_site_id", "site_id"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    route_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("dive_routes.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[Optional[str]] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    days_suggested: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class Incident(Base, TimestampMixin):
    """Incident intelligence — anonymized/aggregated where needed."""

    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_site_id", "site_id"),
        Index("ix_incidents_kind", "kind"),
        Index("ix_incidents_occurred_on", "occurred_on"),
        Index("ix_incidents_geom", "geom", postgresql_using="gist"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    site_id: Mapped[Optional[str]] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    occurred_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    depth_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    factors: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    geom: Mapped[Optional[object]] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.4)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class EcoEvent(Base, TimestampMixin):
    """Reef health / biodiversity / MPA change events."""

    __tablename__ = "eco_events"
    __table_args__ = (
        Index("ix_eco_events_site_id", "site_id"),
        Index("ix_eco_events_type", "event_type"),
        Index("ix_eco_events_window", "window_start", "window_end"),
        Index("ix_eco_events_geom", "geom", postgresql_using="gist"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    site_id: Mapped[Optional[str]] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="SET NULL"), nullable=True
    )
    region_id: Mapped[Optional[str]] = mapped_column(
        UUID_PK, ForeignKey("regions.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0–1
    window_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    window_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    geom: Mapped[Optional[object]] = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class SiteEncyclopedia(Base, TimestampMixin):
    """Structured content page for a site — geology, ecology, history, media canon."""

    __tablename__ = "site_encyclopedia"
    __table_args__ = (UniqueConstraint("site_id", name="uq_site_encyclopedia_site"),)

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    site_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="CASCADE"), nullable=False
    )
    geology: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ecology: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    history: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    famous_dives: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_canon: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    # [{title, url, kind: photo|video|article, year}]
    bibliography: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class SurveyAsset(Base, TimestampMixin):
    """Cave surveys, wreck plans, bathymetry, photogrammetry — AR/VR feedstock."""

    __tablename__ = "survey_assets"
    __table_args__ = (
        Index("ix_survey_assets_site_id", "site_id"),
        Index("ix_survey_assets_kind", "kind"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    site_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    format: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # geojson | gltf | obj | pdf | image | other
    captured_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    license: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    geom: Mapped[Optional[object]] = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class Sighting(Base, TimestampMixin):
    """Citizen-science sighting logged against the stable site ontology."""

    __tablename__ = "sightings"
    __table_args__ = (
        Index("ix_sightings_site_id", "site_id"),
        Index("ix_sightings_taxon", "taxon"),
        Index("ix_sightings_observed_at", "observed_at"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    site_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="CASCADE"), nullable=False
    )
    taxon: Mapped[str] = mapped_column(String(200), nullable=False)
    # free or GBIF/WoRMS id in properties
    count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    observer: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
