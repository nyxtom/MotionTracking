from __future__ import annotations

from slugify import slugify

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.ingest.type_map import osm_tags_to_types
from dive_atlas.schemas import DiveSiteIn
from dive_atlas.taxonomy import SourceKind, WaterType

# Prefer mirrors when main Overpass is busy
OVERPASS_ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Continental / ocean basins — keeps queries under timeout
REGIONS: list[tuple[str, float, float, float, float]] = [
    ("caribbean", 7.0, -95.0, 28.0, -58.0),
    ("florida_gulf", 23.0, -98.0, 32.0, -79.0),
    ("mediterranean", 30.0, -10.0, 46.0, 37.0),
    ("red_sea", 12.0, 32.0, 30.0, 44.0),
    ("north_europe", 48.0, -15.0, 72.0, 40.0),
    ("se_asia", -12.0, 95.0, 25.0, 140.0),
    ("east_asia", 20.0, 115.0, 46.0, 150.0),
    ("japan_okinawa", 24.0, 122.0, 46.0, 146.0),
    ("oceania", -50.0, 110.0, 0.0, 180.0),
    ("pacific_islands", -25.0, 130.0, 25.0, -140.0),
    ("east_pacific", -40.0, -120.0, 40.0, -70.0),
    ("south_africa", -40.0, 10.0, -20.0, 40.0),
    ("indian_ocean", -30.0, 40.0, 25.0, 100.0),
    ("hawaii", 18.0, -161.0, 23.0, -154.0),
]


def _query_for_bbox(south: float, west: float, north: float, east: float) -> str:
    bbox = f"{south},{west},{north},{east}"
    return f"""
    [out:json][timeout:90];
    (
      node["sport"="scuba_diving"]({bbox});
      way["sport"="scuba_diving"]({bbox});
      node["scuba_diving"]({bbox});
      way["scuba_diving"]({bbox});
      node["seamark:type"="wreck"]({bbox});
      way["seamark:type"="wreck"]({bbox});
      node["historic"="wreck"]({bbox});
      way["historic"="wreck"]({bbox});
      node["wreck"="yes"]({bbox});
      node["natural"="cave"]["sport"="scuba_diving"]({bbox});
      node["leisure"="diving"]({bbox});
    );
    out center tags;
    """


@register_adapter
class OsmOverpassAdapter(CrawlerAdapter):
    """OpenStreetMap scuba / wreck / dive nodes via Overpass."""

    slug = "osm-overpass"
    name = "OpenStreetMap Overpass (scuba + wrecks)"
    kind = SourceKind.OPEN_DATA

    def __init__(self, *, regions: list[tuple[str, float, float, float, float]] | None = None) -> None:
        self.regions = regions or REGIONS

    def fetch(self) -> IngestBatch:
        seen: set[str] = set()
        sites: list[DiveSiteIn] = []
        with HttpFetcher(min_interval_s=1.0, timeout=120.0) as http:
            for name, south, west, north, east in self.regions:
                data = self._query_region(http, south, west, north, east)
                for el in data.get("elements") or []:
                    site = self._element_to_site(el, region_hint=name)
                    if site is None:
                        continue
                    if site.external_id in seen:
                        continue
                    seen.add(site.external_id or site.slug or site.name)
                    sites.append(site)
        return IngestBatch(
            source_slug=self.slug,
            source_name=self.name,
            source_kind=self.kind,
            sites=sites,
            meta={"regions": len(self.regions), "sites": len(sites)},
        )

    def _query_region(
        self, http: HttpFetcher, south: float, west: float, north: float, east: float
    ) -> dict:
        query = _query_for_bbox(south, west, north, east)
        last_err: Exception | None = None
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                # Overpass wants POST form body
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
            lat = el["center"]["lat"]
            lon = el["center"]["lon"]
        elif "lat" in el and "lon" in el:
            lat = el["lat"]
            lon = el["lon"]
        else:
            return None
        name = tags.get("name") or tags.get("name:en") or f"OSM {el.get('type')}/{el.get('id')}"
        osm_id = f"{el.get('type')}/{el.get('id')}"
        types = osm_tags_to_types(tags)
        water = WaterType.FRESH.value if tags.get("natural") == "cave" else WaterType.SALT.value
        if tags.get("water") in {"lake", "pond", "river"}:
            water = WaterType.FRESH.value
        return DiveSiteIn(
            slug=f"osm-{slugify(osm_id)}-{slugify(name)}"[:240],
            name=name,
            site_types=types,
            water_type=water,
            locality=tags.get("addr:city") or tags.get("is_in") or region_hint,
            description=tags.get("description") or tags.get("note"),
            depth_max_m=_float_or_none(tags.get("depth") or tags.get("maxdepth")),
            lon=float(lon),
            lat=float(lat),
            tags=["osm", region_hint, *types],
            confidence=0.7,
            external_id=osm_id,
            external_url=f"https://www.openstreetmap.org/{osm_id}",
            properties={"osm_tags": tags, "region_hint": region_hint},
            raw=el,
        )


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace("m", "").strip())
    except ValueError:
        return None
