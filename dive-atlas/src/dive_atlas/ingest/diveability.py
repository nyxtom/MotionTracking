"""Heuristics for whether an open-data place belongs in the *underwater* atlas.

Inclusion rule (duh):
  • Underwater / flooded / marine places → keep (flag ``diveable`` + ``access``).
  • Dry terrestrial places → drop (e.g. archaeology caves like Amud / Tabun).

Wikidata's generic ``cave`` (Q35509) class mixes sea caves with show caves,
mines, bunkers, and heritage sites. Only keep caves that look scuba /
flooded / sea-cave related.

Also gates Wikidata shipwreck dumps (Canmore / Unnamed) and OSM dive shops
mis-tagged as sites.
"""

from __future__ import annotations

import re

# Word-boundary aware. Avoid substring traps like "Diversion", "Bosumpra", "Diversas".
_DIVEABLE_CAVE_NAME = re.compile(
    r"""(?ix)
    \bunderwater\b
    | \bscuba\b
    | \bdiving\b
    | \bdiver'?s?\b
    | \bdive\b
    | \bflooded\b
    | \bsump\b
    | \bcenotes?\b
    | \bblue\s+holes?\b
    | \bsea\s+caves?\b
    | \bmarine\s+caves?\b
    | \bsubmerged\b
    | \bcavern\s+dive
    | \bcave\s+dive
    """
)

# Heritage catalog / anonymous wrecks — not curated dive sites.
_JUNK_WRECK_NAME = re.compile(
    r"""(?ix)
    ^(?:unnamed|unknown)\b
    | \bcanmore\b
    | ^Q\d+$
    | \(\s*(?:possibly|probably)\s*\)
    """
)

_INDOOR_POOL_NAME = re.compile(
    r"""(?ix)
    \bhallenbad\b
    | \bzwembad\b
    | \bindoor\s+pool\b
    | \bswimming\s+pool\b
    | \bpiscine\s+municipale\b
    """
)

_OPERATOR_NAME = re.compile(
    r"""(?ix)
    \bdive\s+(?:center|centre|shop|school|club|base|resort)\b
    | \bdiving\s+(?:center|centre|school|club|shop)\b
    | \bscuba\s+(?:center|centre|shop|school|club)\b
    | \bcentro\s+de\s+buceo\b
    | \btauch(?:schule|basis|center|centre)\b
    | \bcentre\s+de\s+plong
    """
)

# Wikidata classes that are dive-relevant without needing a name keyword.
DIVEABLE_CAVE_CLASS_QIDS: frozenset[str] = frozenset(
    {
        "Q1052919",  # sea cave
        "Q1051914",  # cenote
        "Q2046336",  # blue hole
    }
)

# Trusted atlas sources — if a cave arrived via these, keep it even if the
# Wikidata name alone wouldn't pass (e.g. PADI "Devil's Cave").
TRUSTED_SITE_SOURCES: frozenset[str] = frozenset(
    {
        "padi-travel",
        "osm-overpass",
        "dense-hotspots",
        "seed-famous",
        "seed-galapagos-cenotes",
        "seed-habitats",
        "seed-palau-truk",
        "seed-raja-ampat",
        "seed-komodo",
        "seed-sipadan",
    }
)

# Back-compat alias
TRUSTED_CAVE_SOURCES = TRUSTED_SITE_SOURCES


def is_diveable_cave_name(name: str | None) -> bool:
    """True when the label itself implies scuba / flooded / sea cave diving."""
    if not name:
        return False
    return bool(_DIVEABLE_CAVE_NAME.search(name))


def is_diveable_wikidata_cave(
    *,
    name: str | None,
    class_qid: str | None = None,
    class_label: str | None = None,
) -> bool:
    """Gate for Wikidata cave-class rows before they enter the atlas."""
    qid = (class_qid or "").strip()
    if qid in DIVEABLE_CAVE_CLASS_QIDS:
        return True
    label = (class_label or "").strip().lower()
    if label in {"sea cave", "cenote", "blue hole"}:
        return True
    return is_diveable_cave_name(name)


def is_junk_wikidata_wreck_name(name: str | None) -> bool:
    """True for anonymous / Canmore-catalog wrecks that are not dive sites."""
    if not name:
        return True
    return bool(_JUNK_WRECK_NAME.search(name.strip()))


def is_indoor_pool_name(name: str | None) -> bool:
    if not name:
        return False
    return bool(_INDOOR_POOL_NAME.search(name))


def is_operator_name(name: str | None) -> bool:
    if not name:
        return False
    return bool(_OPERATOR_NAME.search(name))


def is_osm_operator_tags(tags: dict | None) -> bool:
    """OSM nodes that are shops / centres, not diveable places."""
    if not tags:
        return False
    tourism = (tags.get("tourism") or "").lower()
    amenity = (tags.get("amenity") or "").lower()
    shop = (tags.get("shop") or "").lower()
    if tourism == "dive_centre":
        return True
    if amenity == "dive_centre":
        return True
    if shop in {"scuba_diving", "dive", "diving"}:
        return True
    # Olympic / pool springboard — not scuba
    if amenity == "spring_board":
        return True
    return False


def is_osm_non_scuba_diving_tags(tags: dict | None) -> bool:
    """sport=diving without scuba usually means pool / cliff diving."""
    if not tags:
        return False
    sport = (tags.get("sport") or "").lower()
    scuba = (tags.get("scuba_diving") or "").lower()
    amenity = (tags.get("amenity") or "").lower()
    if amenity == "spring_board":
        return True
    if sport == "diving" and not scuba and (tags.get("tourism") or "").lower() != "dive_centre":
        # Keep if explicitly a dive spot
        if tags.get("scuba_diving:divespot") == "yes":
            return False
        if "wreck" in (tags.get("historic") or "").lower():
            return False
        return True
    return False
