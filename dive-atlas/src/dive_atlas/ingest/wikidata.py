from __future__ import annotations

import re

from slugify import slugify

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.ingest.type_map import normalize_site_types
from dive_atlas.schemas import DiveSiteIn
from dive_atlas.taxonomy import SourceKind, WaterType

SPARQL = "https://query.wikidata.org/sparql"

# instance-of classes that are dive-relevant with coordinates
CLASSES: list[tuple[str, str, str]] = [
    ("Q852190", "wreck", "shipwreck"),
    ("Q1051914", "cenote", "cenote"),
    ("Q184358", "reef", "reef"),
    ("Q2046336", "blue_hole", "blue hole"),
    ("Q35509", "cave", "cave"),
    ("Q570116", "reef", "tourist attraction"),  # filtered later by scuba keywords
]

POINT_RE = re.compile(r"Point\(\s*([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s*\)")


def _parse_point(wkt: str) -> tuple[float, float] | None:
    m = POINT_RE.search(wkt or "")
    if not m:
        return None
    lon, lat = float(m.group(1)), float(m.group(2))
    return lon, lat


@register_adapter
class WikidataAdapter(CrawlerAdapter):
    """Wikidata entities with coordinates: wrecks, cenotes, reefs, caves, blue holes."""

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
                    item = row["item"]["value"]
                    qid_item = item.rsplit("/", 1)[-1]
                    if qid_item in seen:
                        continue
                    name = row.get("itemLabel", {}).get("value") or qid_item
                    if site_type == "reef" and label == "tourist attraction":
                        # Keep only scuba-ish attractions
                        blob = name.lower()
                        if not any(k in blob for k in ("dive", "scuba", "reef", "wreck", "cenote")):
                            continue
                    point = _parse_point(row.get("coord", {}).get("value", ""))
                    if not point:
                        continue
                    lon, lat = point
                    seen.add(qid_item)
                    water = WaterType.FRESH.value if site_type in {"cenote", "cave"} else WaterType.SALT.value
                    sites.append(
                        DiveSiteIn(
                            slug=f"wd-{qid_item}-{slugify(name)}"[:240],
                            name=name,
                            site_types=normalize_site_types(site_type),
                            water_type=water,
                            lon=lon,
                            lat=lat,
                            tags=["wikidata", site_type],
                            confidence=0.65,
                            external_id=qid_item,
                            external_url=item,
                            properties={"wikidata_class": qid, "class_label": label},
                            raw=row,
                        )
                    )
        return IngestBatch(
            source_slug=self.slug,
            source_name=self.name,
            source_kind=self.kind,
            sites=sites,
            meta={"sites": len(sites), "classes": len(CLASSES)},
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
