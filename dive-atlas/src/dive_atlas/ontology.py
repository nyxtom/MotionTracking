"""Product ontology enums — trip design, safety, science, content.

These map the atlas knowledge graph onto:
  trip composer · phenomena calendar · skill gates · site briefings ·
  fleet ops · incidents · reef health · encyclopedia · narrative routes · AR/VR surveys
"""

from __future__ import annotations

from enum import StrEnum


class CertLevel(StrEnum):
    NONE = "none"
    SUPERVISED = "supervised"  # Discover / resort
    OW = "ow"
    AOW = "aow"
    RESCUE = "rescue"
    DIVEMASTER = "divemaster"
    INSTRUCTOR = "instructor"
    NITROX = "nitrox"
    DEEP = "deep"
    WRECK = "wreck"
    DRIFT = "drift"
    NIGHT = "night"
    CAVERN = "cavern"
    INTRO_CAVE = "intro_cave"
    FULL_CAVE = "full_cave"
    TECH_FUNDAMENTALS = "tech_fundamentals"
    DECO = "deco"
    TRIMIX = "trimix"
    CCR = "ccr"
    UNKNOWN = "unknown"


class OverheadClass(StrEnum):
    NONE = "none"  # open water
    LIGHT = "light"  # swim-throughs, wreck swim-through
    CAVERN = "cavern"  # daylight zone
    CAVE = "cave"
    WRECK_PENETRATION = "wreck_penetration"
    UNKNOWN = "unknown"


class CurrentClass(StrEnum):
    NONE = "none"
    MILD = "mild"
    MODERATE = "moderate"
    STRONG = "strong"
    EXTREME = "extreme"
    UNKNOWN = "unknown"


class GasMix(StrEnum):
    AIR = "air"
    NITROX = "nitrox"
    DECO_NITROX = "deco_nitrox"
    TRIMIX = "trimix"
    HELIOX = "heliox"
    OXYGEN = "oxygen"
    SCRUBBER = "ccr"
    UNKNOWN = "unknown"


class PhenomenonType(StrEnum):
    SARDINE_RUN = "sardine_run"
    MANTA_CLEANING = "manta_cleaning"
    MANTA_AGGREGATION = "manta_aggregation"
    WHALE_SHARK = "whale_shark"
    HUMPBACK = "humpback"
    ORCA = "orca"
    TURTLE_NESTING = "turtle_nesting"
    SPAWNING_AGGREGATION = "spawning_aggregation"
    PLANKTON_BLOOM = "plankton_bloom"
    BIOLUMINESCENCE = "bioluminescence"
    UPWELLING = "upwelling"
    THERMOCLINE_EVENT = "thermocline_event"
    JELLYFISH_BLOOM = "jellyfish_bloom"
    CROWN_OF_THORNS = "crown_of_thorns"
    BLEACHING = "bleaching"
    OTHER = "other"


class HazardType(StrEnum):
    CURRENT = "current"
    SURGE = "surge"
    BOAT_TRAFFIC = "boat_traffic"
    SILT_OUT = "silt_out"
    OVERHEAD = "overhead"
    ENTANGLEMENT = "entanglement"
    DEPTH = "depth"
    NARCOSIS = "narcosis"
    COLD = "cold"
    CONTAMINATION = "contamination"
    MARINE_LIFE = "marine_life"
    ENTRY_EXIT = "entry_exit"
    REMOTENESS = "remoteness"
    OTHER = "other"


class IncidentKind(StrEnum):
    FATALITY = "fatality"
    NEAR_MISS = "near_miss"
    DCI = "dci"
    LOST_DIVER = "lost_diver"
    BOAT = "boat"
    EQUIPMENT = "equipment"
    OTHER = "other"


class EcoEventType(StrEnum):
    BLEACHING = "bleaching"
    COTS_OUTBREAK = "cots_outbreak"
    INVASIVE = "invasive"
    DISEASE = "disease"
    STORM_DAMAGE = "storm_damage"
    SILTATION = "siltation"
    EROSION = "erosion"
    RECOVERY = "recovery"
    MPA_CHANGE = "mpa_change"


class TaxonGroup(StrEnum):
    FISH = "fish"
    SHARK = "shark"
    RAY = "ray"
    MAMMAL = "mammal"
    REPTILE = "reptile"
    INVERT = "invert"
    CORAL = "coral"
    PLANT = "plant"
    OTHER = "other"


class RouteKind(StrEnum):
    WRECK_TRAIL = "wreck_trail"
    CENOTE_SPINE = "cenote_spine"
    ATOLL_CHAIN = "atoll_chain"
    WALL_RUN = "wall_run"
    PELAGIC_CIRCUIT = "pelagic_circuit"
    CAVE_SYSTEM = "cave_system"
    HISTORICAL = "historical"
    CUSTOM = "custom"


class SurveyAssetKind(StrEnum):
    CAVE_SURVEY = "cave_survey"
    WRECK_PLAN = "wreck_plan"
    BATHYMETRY = "bathymetry"
    PHOTOGRAMMETRY = "photogrammetry"
    SIDE_SCAN = "side_scan"
    VR_SCENE = "vr_scene"
    OTHER = "other"
