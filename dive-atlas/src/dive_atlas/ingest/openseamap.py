"""OpenSeaMap / OSM seamarks — boat-chart features as dive-atlas candidates.

Pulls moorings, wrecks, and rocks (the dive-relevant seamark set) via Overpass
across the same coastal tiles as osm-overpass. This is the open analogue of
'Google Maps for boats' point features.
"""

from __future__ import annotations

from slugify import slugify

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.ingest.osm import OVERPASS_ENDPOINTS, REGIONS, _float_or_none
from dive_atlas.ingest.type_map import normalize_site_types
from dive_atlas.schemas import DiveSiteIn
from dive_atlas.services.geo_enrich import area_for_point, country_bbox_for_point
from dive_atlas.taxonomy import SourceKind, WaterType

# Dive-relevant seamark types (IHO / OpenSeaMap).
SEAMARK_TYPES = (
    "mooring",
    "wreck",
    "rock",
    "anchorage",
    "anchor_berth",
)


def _seamark_query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"{south},{west},{north},{east}"
    parts = []
    for t in SEAMARK_TYPES:
        parts.append(f'node["seamark:type"="{t}"]({bbox});')
        parts.append(f'way["seamark:type"="{t}"]({bbox});')
    # Also natural reefs (charted reef polygons/nodes)
    parts.append(f'node["natural"="reef"]({bbox});')
    parts.append(f'way["natural"="reef"]({bbox});')
    joined = "\n      ".join(parts)
    return f"""
    [out:json][timeout:75];
    (
      {joined}
    );
    out center tags;
    """


@register_adapter
class OpenSeaMapAdapter(CrawlerAdapter):
    """OpenSeaMap seamarks + natural reefs (boat chart points)."""

    slug = "openseamap"
    name = "OpenSeaMap seamarks (mooring/wreck/rock/reef)"
    kind = SourceKind.OPEN_DATA

    def __init__(self, *, regions: list[tuple[str, float, float, float, float]] | None = None) -> None:
        self.regions = regions or REGIONS

    def fetch(self) -> IngestBatch:
        sites: list[DiveSiteIn] = []
        seen: set[str] = set()
        errors: list[str] = []
        with HttpFetcher(min_interval_s=1.0, timeout=100.0) as http:
            for name, south, west, north, east in self.regions:
                try:
                    data = self._query_region(http, south, west, north, east)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{name}: {exc}")
                    continue
                added = 0
                for el in data.get("elements") or []:
                    site = self._element_to_site(el, region_hint=name)
                    if site is None:
                        continue
                    key = site.external_id or site.slug
                    if key in seen:
                        continue
                    seen.add(key)
                    sites.append(site)
                    added += 1
                print(
                    f"  openseamap {name}: +{added} (total={len(sites)}) errors={len(errors)}",
                    flush=True,
                )
        return IngestBatch(
            source_slug=self.slug,
            source_name=self.name,
            source_kind=self.kind,
            sites=sites,
            meta={"regions": len(self.regions), "sites": len(sites), "errors": errors},
        )

    def _query_region(
        self, http: HttpFetcher, south: float, west: float, north: float, east: float
    ) -> dict:
        query = _seamark_query(south, west, north, east)
        last_err: Exception | None = None
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                http._throttle()
                resp = http._client.post(endpoint, data={"data": query})
                if resp.status_code >= 400:
                    last_err = RuntimeError(f"{endpoint} -> {resp.status_code}")
                    continue
                data = resp.json()
                if "elements" in data:
                    return data
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
        if last_err:
            raise last_err
        return {"elements": []}

    def _element_to_site(self, el: dict, *, region_hint: str) -> DiveSiteIn | None:
        tags = el.get("tags") or {}
        if el.get("type") == "way" and "center" in el:
            lat = float(el["center"]["lat"])
            lon = float(el["center"]["lon"])
        elif "lat" in el and "lon" in el:
            lat = float(el["lat"])
            lon = float(el["lon"])
        else:
            return None

        seamark = (tags.get("seamark:type") or "").lower()
        natural = (tags.get("natural") or "").lower()
        name = (
            tags.get("name")
            or tags.get("name:en")
            or tags.get("seamark:name")
            or tags.get("seamark:wreck:name")
            or ""
        ).strip()
        if not name:
            name = f"Seamark {seamark or natural} {el.get('type')}/{el.get('id')}"

        types: list[str] = []
        if seamark == "wreck" or tags.get("historic") == "wreck":
            types.append("wreck")
        if seamark in {"mooring", "anchorage", "anchor_berth"}:
            types.append("reef")  # dive-boat drop — often on reef; tag as seamark
        if seamark == "rock":
            types.append("reef")
        if natural == "reef":
            types.append("reef")
        types = normalize_site_types(*types)

        area = area_for_point(lat, lon)
        country = area.country_code if area else None
        locality = tags.get("addr:city") or (area.name if area else None) or region_hint
        if not country:
            bbox = country_bbox_for_point(lat, lon)
            if bbox:
                country = bbox.country_code

        osm_id = f"{el.get('type')}/{el.get('id')}"
        depth = _float_or_none(
            tags.get("depth")
            or tags.get("seamark:wreck:depth")
            or tags.get("seamark:rock:depth")
        )
        return DiveSiteIn(
            slug=f"osm-sea-{slugify(osm_id)}-{slugify(name)}"[:240],
            name=name,
            site_types=types,
            water_type=WaterType.SALT.value,
            country_code=country,
            locality=locality,
            description=tags.get("description") or tags.get("note"),
            depth_max_m=depth,
            lon=lon,
            lat=lat,
            tags=["openseamap", "seamark", seamark or natural, region_hint, *types],
            confidence=0.7,
            external_id=osm_id,
            external_url=f"https://www.openstreetmap.org/{osm_id}",
            properties={"osm_tags": tags, "seamark_type": seamark or natural},
            raw={"type": el.get("type"), "id": el.get("id"), "tags": tags},
        )
