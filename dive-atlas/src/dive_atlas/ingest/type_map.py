from __future__ import annotations

"""Map PADI / OSM / free-text dive types onto atlas SiteType values."""

from dive_atlas.taxonomy import SiteType

_PADI_MAP = {
    "reef": SiteType.REEF,
    "wall": SiteType.WALL,
    "wreck": SiteType.WRECK,
    "cave": SiteType.CAVE,
    "cavern": SiteType.CAVERN,
    "cenote": SiteType.CENOTE,
    "drift": SiteType.DRIFT,
    "muck": SiteType.MUCK,
    "ocean": SiteType.REEF,
    "lake": SiteType.LAKE,
    "river": SiteType.RIVER,
    "quarry": SiteType.QUARRY,
    "blue hole": SiteType.BLUE_HOLE,
    "bluehole": SiteType.BLUE_HOLE,
    "pinnacle": SiteType.PINNACLE,
    "seamount": SiteType.SEAMOUNT,
    "lagoon": SiteType.LAGOON,
    "atoll": SiteType.ATOLL,
    "artificial reef": SiteType.ARTIFICIAL_REEF,
    "jetty": SiteType.JETTY,
    "pier": SiteType.PIER,
    "macro": SiteType.MUCK,
    "night": SiteType.UNKNOWN,
    "deep": SiteType.UNKNOWN,
    "beginner": SiteType.UNKNOWN,
}


def normalize_site_types(*raw_types: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_types:
        if not raw:
            continue
        key = raw.strip().lower()
        mapped = _PADI_MAP.get(key)
        if mapped is None:
            # fuzzy contains
            for needle, site_type in _PADI_MAP.items():
                if needle in key:
                    mapped = site_type
                    break
        value = (mapped or SiteType.UNKNOWN).value
        if value == SiteType.UNKNOWN.value:
            continue
        if value not in seen:
            seen.add(value)
            out.append(value)
    if not out:
        out.append(SiteType.UNKNOWN.value)
    return out


def osm_tags_to_types(tags: dict[str, str]) -> list[str]:
    types: list[str] = []
    scuba = (tags.get("scuba_diving") or "").lower()
    sport = (tags.get("sport") or "").lower()
    natural = (tags.get("natural") or "").lower()
    historic = (tags.get("historic") or "").lower()
    wreck = (tags.get("wreck") or tags.get("seamark:type") or "").lower()
    water = (tags.get("water") or "").lower()

    if "wreck" in wreck or historic == "wreck" or tags.get("seamark:type") == "wreck":
        types.append(SiteType.WRECK.value)
    if natural == "cave" or "cave" in scuba:
        types.append(SiteType.CAVE.value)
    if "cenote" in (tags.get("name") or "").lower() or tags.get("cenote"):
        types.append(SiteType.CENOTE.value)
    if natural == "reef" or tags.get("reef") or "reef" in scuba:
        types.append(SiteType.REEF.value)
    if sport == "scuba_diving" or scuba in {"yes", "scuba"}:
        if not types:
            types.append(SiteType.REEF.value)
    if water in {"lake", "pond"}:
        types.append(SiteType.LAKE.value)
    if tags.get("man_made") == "pier":
        types.append(SiteType.PIER.value)
    return normalize_site_types(*types)
