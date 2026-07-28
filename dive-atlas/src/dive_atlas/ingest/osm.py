from __future__ import annotations

from slugify import slugify

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.ingest.type_map import osm_tags_to_types
from dive_atlas.schemas import DiveSiteIn
from dive_atlas.services.geo_enrich import area_for_point, country_bbox_for_point
from dive_atlas.taxonomy import SourceKind, WaterType

OVERPASS_ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Dense regional tiles around known dive concentrations + broad coastal bands.
# Smaller tiles = fewer Overpass timeouts and better site density.
REGIONS: list[tuple[str, float, float, float, float]] = [
    # Americas
    ("florida", 24.0, -88.0, 31.5, -79.5),
    ("florida_keys", 24.3, -82.0, 25.3, -80.0),
    ("n_florida_springs", 29.5, -84.0, 30.6, -82.0),
    ("california", 32.0, -125.0, 42.5, -116.0),
    ("hawaii", 18.5, -160.5, 22.5, -154.5),
    ("pacific_nw", 42.0, -129.0, 49.5, -122.0),
    ("gulf_mexico", 25.5, -98.0, 30.5, -82.0),
    ("yucatan_cenotes", 19.8, -88.0, 21.8, -86.6),
    ("cozumel_riviera", 19.8, -87.5, 21.0, -86.6),
    ("bay_islands_hn", 15.8, -87.3, 16.7, -85.6),
    ("belize_barrier", 15.8, -89.0, 18.5, -87.3),
    ("utila_roatan", 16.0, -87.2, 16.5, -86.2),
    ("costa_rica_pacific", 8.0, -87.0, 11.2, -83.0),
    ("panama", 7.0, -83.0, 9.8, -77.0),
    ("colombia_carib", 8.0, -77.5, 12.6, -71.0),
    ("cuba", 19.7, -85.0, 23.3, -74.0),
    ("jamaica", 17.6, -78.5, 18.6, -76.1),
    ("bahamas", 20.9, -79.5, 27.3, -72.5),
    ("cayman", 19.2, -81.5, 19.8, -79.6),
    ("lesser_antilles", 10.0, -68.0, 19.0, -59.0),
    ("bonaire_curacao", 11.8, -69.5, 12.5, -68.0),
    ("brazil_ne", -10.0, -40.0, -2.0, -32.0),
    ("brazil_se", -28.0, -49.0, -20.0, -39.0),
    ("galapagos", -1.6, -92.2, 1.5, -89.0),
    # Europe / Med / UK
    ("uk_scapa", 48.0, -12.0, 62.0, 3.0),
    ("scotland_orkney", 58.5, -4.0, 59.5, -2.0),
    ("med_west", 35.0, -6.0, 45.0, 15.0),
    ("med_east", 30.0, 15.0, 42.0, 37.0),
    ("croatia_adriatic", 42.3, 15.0, 45.5, 19.0),
    ("greece_aegean", 34.5, 19.0, 41.5, 29.5),
    ("malta_gozo", 35.7, 14.1, 36.2, 14.7),
    ("canaries", 27.5, -18.5, 29.5, -13.3),
    ("azores", 36.8, -31.5, 39.8, -24.8),
    ("iceland", 63.0, -25.0, 67.0, -13.0),
    ("norway_fjords", 58.0, 4.0, 71.0, 32.0),
    # Red Sea / Africa / MidEast
    ("red_sea", 12.0, 32.0, 30.0, 44.0),
    ("egypt_sinai", 27.5, 33.5, 29.5, 35.0),
    ("egypt_hurghada", 26.5, 33.5, 28.0, 34.6),
    ("jordan_aqaba", 29.2, 34.8, 29.6, 35.1),
    ("sudan_red_sea", 18.0, 36.5, 22.5, 39.0),
    ("south_africa", -35.0, 16.0, -26.0, 34.0),
    ("mozambique", -27.0, 32.0, -10.0, 41.0),
    ("tanzania_zanzibar", -7.0, 38.5, -4.5, 40.5),
    ("seychelles", -10.5, 45.5, -3.5, 56.5),
    ("mauritius", -21.0, 56.5, -19.8, 58.0),
    # Indian Ocean / SE Asia
    ("maldives", -1.5, 72.0, 7.5, 74.0),
    ("sri_lanka", 5.8, 79.5, 10.0, 82.0),
    ("andaman", 6.5, 92.0, 14.0, 94.5),
    ("thailand_andaman", 6.5, 97.0, 10.5, 99.5),
    ("thailand_gulf", 9.0, 99.0, 13.5, 102.0),
    ("malaysia_east", 1.0, 102.0, 7.5, 119.5),
    ("malaysia_west", 1.0, 99.5, 7.0, 103.5),
    ("indonesia_west", -12.0, 95.0, 8.0, 120.0),
    ("indonesia_east", -10.0, 120.0, 5.0, 141.0),
    ("bali_komodo", -9.2, 114.3, -7.8, 120.0),
    ("raja_ampat", -1.5, 129.5, 0.5, 131.5),
    ("bunaken_lembeh", 1.2, 124.4, 1.9, 125.4),
    ("philippines", 5.0, 116.0, 21.0, 127.0),
    ("coron_palawan", 9.0, 117.5, 12.5, 121.0),
    ("visayas", 9.0, 121.5, 12.5, 125.0),
    ("vietnam", 8.0, 102.0, 22.0, 110.0),
    # East Asia / Pacific
    ("okinawa_yaeyama", 24.0, 123.0, 27.0, 129.0),
    ("okinawa_main", 26.0, 127.4, 27.0, 128.4),
    ("japan_izu", 34.0, 138.5, 35.5, 140.0),
    ("korea_jeju", 33.0, 124.0, 39.0, 132.0),
    ("taiwan", 21.8, 119.5, 25.4, 122.1),
    ("guam_mariana", 13.0, 144.5, 15.5, 146.0),
    ("palau", 2.8, 131.0, 8.2, 134.8),
    ("micronesia_truk", 5.0, 145.0, 12.0, 155.0),
    ("yap", 9.3, 137.8, 9.8, 138.4),
    ("fiji", -21.0, 176.8, -15.5, -178.0),
    ("vanuatu", -20.5, 166.0, -13.0, 170.5),
    ("new_caledonia", -23.0, 163.5, -19.5, 168.5),
    ("french_polynesia", -18.0, -150.0, -14.0, -147.0),
    ("png_solomons", -12.0, 140.0, 0.0, 163.0),
    ("kimbe_milne", -10.5, 147.0, -4.5, 153.0),
    ("australia_east", -45.0, 140.0, -10.0, 155.0),
    ("gbr_cairns", -18.5, 145.5, -14.0, 147.5),
    ("australia_west", -35.0, 112.0, -15.0, 130.0),
    ("ningaloo", -24.0, 113.0, -21.0, 114.5),
    ("new_zealand", -48.0, 166.0, -34.0, 179.0),
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
      node["tourism"="dive_centre"]({bbox});
      node["amenity"="dive_centre"]({bbox});
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
                print(
                    f"  osm tile {name}: +elements → total sites={len(sites)} errors={len(errors)}",
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
        area = area_for_point(float(lat), float(lon))
        country = None
        locality = tags.get("addr:city") or tags.get("is_in")
        if area:
            country = area.country_code
            if not locality:
                locality = area.name
        if not country:
            bbox = country_bbox_for_point(float(lat), float(lon))
            if bbox:
                country = bbox.country_code
        if not locality:
            locality = region_hint
        site_tags = ["osm", region_hint, *types]
        if area:
            site_tags.extend([a for a in (area.name.lower(), *area.aliases) if a])
        return DiveSiteIn(
            slug=f"osm-{slugify(osm_id)}-{slugify(name)}"[:240],
            name=name,
            site_types=types,
            water_type=water,
            country_code=country,
            locality=locality,
            description=tags.get("description") or tags.get("note"),
            depth_max_m=_float_or_none(tags.get("depth") or tags.get("maxdepth")),
            lon=float(lon),
            lat=float(lat),
            tags=site_tags,
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
