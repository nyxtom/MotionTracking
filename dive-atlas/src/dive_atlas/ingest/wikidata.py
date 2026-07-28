from __future__ import annotations

import re

from slugify import slugify

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.ingest.diveability import is_diveable_wikidata_cave
from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.ingest.type_map import normalize_site_types
from dive_atlas.schemas import DiveSiteIn
from dive_atlas.services.geo_enrich import area_for_point, country_bbox_for_point
from dive_atlas.taxonomy import SourceKind, WaterType

SPARQL = "https://query.wikidata.org/sparql"

# Dive-relevant Wikidata classes with coordinates.
# IMPORTANT: do NOT ingest generic cave (Q35509) unfiltered — that pulls
# archaeology / dry show caves (Amud, Tabun, Kanheri, …). Sea caves and
# keyword-filtered flooded/underwater caves are handled separately below.
CLASSES: list[tuple[str, str, str]] = [
    ("Q852190", "wreck", "shipwreck"),
    ("Q1051914", "cenote", "cenote"),
    ("Q184358", "reef", "reef"),
    ("Q2046336", "blue_hole", "blue hole"),
    ("Q1052919", "cave", "sea cave"),
    ("Q570116", "reef", "tourist attraction"),  # filtered later by scuba keywords
]

# Generic caves only when the English label implies diving / flooding / sea cave.
_CAVE_LABEL_SPARQL = r"underwater|scuba|diving|\\bdive\\b|flooded|\\bsump\\b|cenote|blue hole|sea cave|marine cave|submerged"

POINT_RE = re.compile(r"Point\(\s*([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s*\)")


def _parse_point(wkt: str) -> tuple[float, float] | None:
    m = POINT_RE.search(wkt or "")
    if not m:
        return None
    lon, lat = float(m.group(1)), float(m.group(2))
    return lon, lat


@register_adapter
class WikidataAdapter(CrawlerAdapter):
    """Wikidata entities with coordinates: wrecks, cenotes, reefs, sea/flooded caves, blue holes."""

    slug = "wikidata"
    name = "Wikidata dive-relevant places"
    kind = SourceKind.OPEN_DATA

    def __init__(self, *, limit_per_class: int = 5000) -> None:
        self.limit_per_class = limit_per_class

    def fetch(self) -> IngestBatch:
        sites: list[DiveSiteIn] = []
        seen: set[str] = set()
        with HttpFetcher(
            min_interval_s=0.5,
            headers={
                "Accept": "application/sparql-results+json",
                "User-Agent": "DiveAtlas/0.1 (https://github.com/nyxtom; research)",
            },
        ) as http:
            for qid, site_type, label in CLASSES:
                rows = self._query_class(http, qid)
                for row in rows:
                    site = self._row_to_site(
                        row,
                        class_qid=qid,
                        site_type=site_type,
                        label=label,
                        seen=seen,
                    )
                    if site:
                        sites.append(site)
            # Keyword-gated generic caves (never unfiltered Q35509).
            for row in self._query_diveable_caves(http):
                site = self._row_to_site(
                    row,
                    class_qid="Q35509",
                    site_type="cave",
                    label="cave (dive-keyword)",
                    seen=seen,
                    require_diveable_cave=True,
                )
                if site:
                    sites.append(site)
        return IngestBatch(
            source_slug=self.slug,
            source_name=self.name,
            source_kind=self.kind,
            sites=sites,
            meta={"sites": len(sites), "classes": len(CLASSES) + 1},
        )

    def _row_to_site(
        self,
        row: dict,
        *,
        class_qid: str,
        site_type: str,
        label: str,
        seen: set[str],
        require_diveable_cave: bool = False,
    ) -> DiveSiteIn | None:
        item = row["item"]["value"]
        qid_item = item.rsplit("/", 1)[-1]
        if qid_item in seen:
            return None
        name = row.get("itemLabel", {}).get("value") or qid_item
        if site_type == "reef" and label == "tourist attraction":
            blob = name.lower()
            if not any(k in blob for k in ("dive", "scuba", "reef", "wreck", "cenote")):
                return None
        if site_type == "cave" or require_diveable_cave:
            # Sea caves (Q1052919) pass via class; generic caves need name evidence.
            if not is_diveable_wikidata_cave(
                name=name, class_qid=class_qid, class_label=label
            ):
                return None
        point = _parse_point(row.get("coord", {}).get("value", ""))
        if not point:
            return None
        lon, lat = point
        seen.add(qid_item)
        water = WaterType.FRESH.value if site_type in {"cenote", "cave"} else WaterType.SALT.value
        if label == "sea cave":
            water = WaterType.SALT.value
        area = area_for_point(lat, lon)
        country = area.country_code if area else None
        locality = area.name if area else None
        if not country:
            bbox = country_bbox_for_point(lat, lon)
            if bbox:
                country = bbox.country_code
        site_tags = ["wikidata", site_type]
        if label == "sea cave":
            site_tags.append("sea_cave")
        if area:
            site_tags.extend([a for a in (area.name.lower(), *area.aliases) if a])
        confidence = 0.65
        if site_type == "cave" and class_qid == "Q35509":
            confidence = 0.55  # name-keyword only; still provisional
        return DiveSiteIn(
            slug=f"wd-{qid_item}-{slugify(name)}"[:240],
            name=name,
            site_types=normalize_site_types(site_type),
            water_type=water,
            country_code=country,
            locality=locality,
            lon=lon,
            lat=lat,
            tags=site_tags,
            confidence=confidence,
            external_id=qid_item,
            external_url=item,
            properties={"wikidata_class": class_qid, "class_label": label},
            raw=row,
        )

    def _query_class(self, http: HttpFetcher, class_qid: str) -> list[dict]:
        query = f"""
        SELECT ?item ?itemLabel ?coord WHERE {{
          ?item wdt:P31/wdt:P279* wd:{class_qid} ;
                wdt:P625 ?coord .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
        }}
        LIMIT {self.limit_per_class}
        """
        data = http.get_json(SPARQL, params={"query": query, "format": "json"})
        return data.get("results", {}).get("bindings", [])

    def _query_diveable_caves(self, http: HttpFetcher) -> list[dict]:
        """Generic caves whose English label implies diving / flooding / sea cave."""
        query = f"""
        SELECT ?item ?itemLabel ?coord WHERE {{
          ?item wdt:P31/wdt:P279* wd:Q35509 ;
                wdt:P625 ?coord .
          ?item rdfs:label ?itemLabel .
          FILTER(LANG(?itemLabel) = "en")
          FILTER(REGEX(LCASE(STR(?itemLabel)), "{_CAVE_LABEL_SPARQL}"))
        }}
        LIMIT {self.limit_per_class}
        """
        data = http.get_json(SPARQL, params={"query": query, "format": "json"})
        return data.get("results", {}).get("bindings", [])
