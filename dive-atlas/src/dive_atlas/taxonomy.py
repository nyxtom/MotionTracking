"""Dive site and feature taxonomy.

Covers the full atlas surface: reefs, caves, cenotes, wrecks, atolls, walls,
blue holes, muck, freshwater, ice, and more. Sites may carry multiple types
(e.g. cavern + cenote, reef + wall).
"""

from __future__ import annotations

from enum import StrEnum


class SiteType(StrEnum):
    REEF = "reef"
    WALL = "wall"
    WRECK = "wreck"
    CAVE = "cave"
    CAVERN = "cavern"
    CENOTE = "cenote"
    ATOLL = "atoll"
    LAGOON = "lagoon"
    BLUE_HOLE = "blue_hole"
    PINNACLE = "pinnacle"
    SEAMOUNT = "seamount"
    DRIFT = "drift"
    MUCK = "muck"
    ARTIFICIAL_REEF = "artificial_reef"
    QUARRY = "quarry"
    LAKE = "lake"
    RIVER = "river"
    SPRING = "spring"
    ICE = "ice"
    JETTY = "jetty"
    PIER = "pier"
    CANAL = "canal"
    PASS = "pass"
    CHANNEL = "channel"
    DROP_OFF = "drop_off"
    SAND_FLAT = "sand_flat"
    MANGROVE = "mangrove"
    UNKNOWN = "unknown"


class WaterType(StrEnum):
    SALT = "salt"
    FRESH = "fresh"
    BRACKISH = "brackish"
    MIXED = "mixed"


class AccessKind(StrEnum):
    """Who can dive here — atlas includes non-recreational places too."""

    RECREATIONAL = "recreational"  # normal public / charter dive site
    RESTRICTED = "restricted"  # permit, guide-only, military, etc.
    RESEARCH_ONLY = "research_only"  # habitats / labs (e.g. Aquarius)
    PRIVATE = "private"  # private property / resort house reef locked
    CLOSED = "closed"  # historically diveable, now closed
    UNKNOWN = "unknown"


class EntryType(StrEnum):
    BOAT = "boat"
    SHORE = "shore"
    BOTH = "both"
    LIVEABOARD = "liveaboard"
    UNKNOWN = "unknown"


class SkillLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    TECHNICAL = "technical"
    CAVE_TRAINED = "cave_trained"
    UNKNOWN = "unknown"


class RegionKind(StrEnum):
    OCEAN = "ocean"
    SEA = "sea"
    ARCHIPELAGO = "archipelago"
    COUNTRY = "country"
    STATE = "state"
    PROVINCE = "province"
    ISLAND = "island"
    ATOLL_GROUP = "atoll_group"
    COAST = "coast"
    PARK = "park"
    CUSTOM = "custom"


class SourceKind(StrEnum):
    SEED = "seed"
    OPEN_DATA = "open_data"
    MAGAZINE = "magazine"
    TRAVEL_SITE = "travel_site"
    PLACES_API = "places_api"
    USER = "user"
    GIS = "gis"
    OTHER = "other"


# Human-readable labels for CLI / future UI
SITE_TYPE_LABELS: dict[SiteType, str] = {
    SiteType.REEF: "Reef",
    SiteType.WALL: "Wall",
    SiteType.WRECK: "Wreck",
    SiteType.CAVE: "Cave",
    SiteType.CAVERN: "Cavern",
    SiteType.CENOTE: "Cenote",
    SiteType.ATOLL: "Atoll",
    SiteType.LAGOON: "Lagoon",
    SiteType.BLUE_HOLE: "Blue hole",
    SiteType.PINNACLE: "Pinnacle",
    SiteType.SEAMOUNT: "Seamount",
    SiteType.DRIFT: "Drift",
    SiteType.MUCK: "Muck",
    SiteType.ARTIFICIAL_REEF: "Artificial reef",
    SiteType.QUARRY: "Quarry",
    SiteType.LAKE: "Lake",
    SiteType.RIVER: "River",
    SiteType.SPRING: "Spring",
    SiteType.ICE: "Ice",
    SiteType.JETTY: "Jetty",
    SiteType.PIER: "Pier",
    SiteType.CANAL: "Canal",
    SiteType.PASS: "Pass",
    SiteType.CHANNEL: "Channel",
    SiteType.DROP_OFF: "Drop-off",
    SiteType.SAND_FLAT: "Sand flat",
    SiteType.MANGROVE: "Mangrove",
    SiteType.UNKNOWN: "Unknown",
}
