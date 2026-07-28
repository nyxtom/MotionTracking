"""Heuristics for whether an open-data place is a *diveable* site.

Wikidata's generic ``cave`` (Q35509) class includes archaeology, dry show caves,
mines, and bunkers. Only keep caves that look scuba / underwater / sea-cave
related — never random terrestrial caves (e.g. Amud / Tabun in Israel).
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
TRUSTED_CAVE_SOURCES: frozenset[str] = frozenset(
    {
        "padi-travel",
        "osm-overpass",
        "dense-hotspots",
        "seed-famous",
        "seed-galapagos-cenotes",
        "seed-palau-truk",
        "seed-raja-ampat",
        "seed-komodo",
        "seed-sipadan",
    }
)


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
