from __future__ import annotations

from slugify import slugify

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.ingest.type_map import osm_tags_to_types
from dive_atlas.schemas import DiveSiteIn
from dive_atlas.taxonomy import SourceKind, WaterType

OVERPASS_ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Smaller tiles = fewer Overpass timeouts
REGIONS: list[tuple[str, float, float, float, float]] = [
    ("florida", 24.0, -88.0, 31.5, -79.5),
    ("yucatan_carib", 15.0, -92.0, 23.5, -60.0),
    ("lesser_antilles", 10.0, -68.0, 19.0, -59.0),
    ("hawaii", 18.5, -160.5, 22.5, -154.5),
    ("california", 32.0, -125.0, 42.5, -116.0),
    ("med_west", 35.0, -6.0, 45.0, 15.0),
    ("med_east", 30.0, 15.0, 42.0, 37.0),
    ("red_sea", 12.0, 32.0, 30.0, 44.0),
    ("uk_scapa", 48.0, -12.0, 62.0, 3.0),
    ("maldives", -1.5, 72.0, 7.5, 74.0),
    ("indonesia_west", -12.0, 95.0, 8.0, 120.0),
    ("indonesia_east", -10.0, 120.0, 5.0, 141.0),
    ("philippines", 5.0, 116.0, 21.0, 127.0),
    ("thailand_malaysia", 1.0, 96.0, 15.0, 105.0),
    ("okinawa_japan", 24.0, 123.0, 46.0, 146.0),
    ("korea", 33.0, 124.0, 39.0, 132.0),
    ("australia_east", -45.0, 140.0, -10.0, 155.0),
    ("png_solomons", -12.0, 140.0, 0.0, 163.0),
    ("micronesia_truk", 5.0, 145.0, 12.0, 155.0),
    ("south_africa", -35.0, 16.0, -26.0, 34.0),
]


def _scuba_query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"{south},{west},{north},{east}"
    # Keep the query scuba-specific; wreck dumps alone can timeout.
    return f"""
    [out:json][timeout:60];
    (
      node["sport"="scuba_diving"]({bbox});
      way["sport"="scuba_diving"]({bbox});
      node["scuba_diving"]({bbox});
      way["scuba_diving"]({bbox});
      node["leisure"="diving"]({bbox});
      node["sport"="diving"]({bbox});
      node["historic"="wreck"]["scuba_diving"]({bbox});
      node["seamark:type"="wreck"]["scuba_diving"]({bbox});
    );
    out center tags;
    """


@register_adapter
class OsmOverpassAdapter(CrawlerAdapter):
    """OpenStreetMap scuba / dive nodes via Overpass (region tiles)."""

    slug = "osm-overpass"
    name = "OpenStreetMap Overpass (scuba + wrecks)"
    kind = SourceKind.OPEN_DATA

    def __init__(self, *, regions: list[tuple[str, float, float, float, float]] | None = None) -> None:
        self.regions = regions or REGIONS

    def fetch(self) -> IngestBatch:
        seen: set[str] = set()
        sites: list[DiveSiteIn] = []
        errors: list[str] = []
        with HttpFetcher(min_interval_s=1.2, timeout=90.0) as http:
            for name, south, west, north, east in self.regions:
                try:
                    data = self._query_region(http, south, west, north, east)
                except Exception as exc:  # noqa: BLE001 — continue other regions
                    errors.append(f"{name}: {exc}")
                    continue
                for el in data.get("elements") or []:
                    site = self._element_to_site(el, region_hint=name)
                    if site is None:
                        continue
                    key = site.external_id or site.slug or site.name
                    if key in seen:
                        continue
                    seen.add(key)
                    sites.append(site)
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
        query = _scuba_query(south, west, north, east)
        last_err: Exception | None = None
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                http._throttle()
                resp = http._client.post(endpoint, data={"data": query})
                if resp.status_code >= 400:
                    last_err = RuntimeError(f"{endpoint} -> {resp.status_code}")
                    continue
                text = resp.text
                if "Error" in text and "elements" not in text:
                    last_err = RuntimeError(text[:200])
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
            raw={"type": el.get("type"), "id": el.get("id"), "tags": tags},
        )


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace("m", "").strip())
    except ValueError:
        return None
