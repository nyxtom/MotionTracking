from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from dive_atlas.models import DiveSite
from dive_atlas.models.capabilities import (
    DiveRoute,
    DiveRouteStop,
    Phenomenon,
    SiteBriefing,
    SiteProfile,
)

SEED_PATH = Path(__file__).resolve().parents[3] / "data" / "seeds" / "product_ontology.json"


def seed_product_ontology(session: Session, path: Path | None = None) -> dict[str, int]:
    data = json.loads((path or SEED_PATH).read_text(encoding="utf-8"))
    stats = {"phenomena": 0, "routes": 0, "stops": 0, "profiles": 0, "briefings": 0}

    for raw in data.get("phenomena", []):
        row = session.scalar(select(Phenomenon).where(Phenomenon.slug == raw["slug"]))
        if row is None:
            row = Phenomenon(slug=raw["slug"], typical_months=[], properties={})
            session.add(row)
        row.name = raw["name"]
        row.phenomenon_type = raw["phenomenon_type"]
        row.description = raw.get("description")
        row.typical_months = raw.get("typical_months") or []
        row.region_slug = raw.get("region_slug")
        stats["phenomena"] += 1

    site_by_slug = {
        s.slug: s
        for s in session.scalars(select(DiveSite)).all()
    }

    for raw in data.get("routes", []):
        route = session.scalar(select(DiveRoute).where(DiveRoute.slug == raw["slug"]))
        if route is None:
            route = DiveRoute(slug=raw["slug"], cert_required=[], tags=[], properties={})
            session.add(route)
        route.name = raw["name"]
        route.kind = raw.get("kind") or "custom"
        route.description = raw.get("description")
        route.estimated_days = raw.get("estimated_days")
        route.cert_required = raw.get("cert_required") or []
        route.tags = raw.get("tags") or []
        session.flush()
        stats["routes"] += 1
        for stop in raw.get("stops") or []:
            existing = session.scalar(
                select(DiveRouteStop).where(
                    DiveRouteStop.route_id == route.id,
                    DiveRouteStop.position == stop["position"],
                )
            )
            if existing is None:
                existing = DiveRouteStop(
                    route_id=route.id, position=stop["position"], properties={}
                )
                session.add(existing)
            site = site_by_slug.get(stop.get("site_slug") or "")
            existing.site_id = site.id if site else None
            existing.title = stop.get("title")
            existing.narrative = stop.get("narrative")
            existing.days_suggested = stop.get("days_suggested")
            stats["stops"] += 1

    for raw in data.get("profiles", []):
        site = site_by_slug.get(raw["site_slug"])
        if not site:
            continue
        row = session.scalar(select(SiteProfile).where(SiteProfile.site_id == site.id))
        if row is None:
            row = SiteProfile(
                site_id=site.id,
                cert_required=[],
                cert_recommended=[],
                gas_mixes=[],
                experiences=[],
                monsoon_months=[],
                best_months=[],
                properties={},
            )
            session.add(row)
        row.cert_required = raw.get("cert_required") or []
        row.cert_recommended = raw.get("cert_recommended") or []
        row.overhead_class = raw.get("overhead_class") or "unknown"
        row.deco_likely = bool(raw.get("deco_likely"))
        row.max_depth_advisory_m = raw.get("max_depth_advisory_m")
        row.current_class = raw.get("current_class") or "unknown"
        row.gas_mixes = raw.get("gas_mixes") or []
        row.surface_support_required = bool(raw.get("surface_support_required"))
        row.beginner_ok = bool(raw.get("beginner_ok"))
        row.experiences = raw.get("experiences") or []
        row.monsoon_months = raw.get("monsoon_months") or []
        row.best_months = raw.get("best_months") or []
        stats["profiles"] += 1

    for raw in data.get("briefings", []):
        site = site_by_slug.get(raw["site_slug"])
        if not site:
            continue
        row = session.scalar(select(SiteBriefing).where(SiteBriefing.site_id == site.id))
        if row is None:
            row = SiteBriefing(
                site_id=site.id, hazards=[], emergency_contacts={}, properties={}
            )
            session.add(row)
        row.entry_exit = raw.get("entry_exit")
        row.currents = raw.get("currents")
        row.thermoclines = raw.get("thermoclines")
        row.overhead_rules = raw.get("overhead_rules")
        row.hazards = raw.get("hazards") or []
        row.hazard_notes = raw.get("hazard_notes")
        row.deco_notes = raw.get("deco_notes")
        row.nearest_chamber = raw.get("nearest_chamber")
        row.nearest_chamber_km = raw.get("nearest_chamber_km")
        row.local_regs = raw.get("local_regs")
        row.marine_park_notes = raw.get("marine_park_notes")
        stats["briefings"] += 1

    session.flush()
    return stats
