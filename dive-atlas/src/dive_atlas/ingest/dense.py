"""Dense hotspot crawler — fine OSM (+ optional PADI map) tiles for dive concentrations.

Boat-drop regions like Raja Ampat / Misool / Wayag are under-represented in
coarse world tiles. This adapter walks named hotspot bboxes at fine grain.
"""

from __future__ import annotations

import json
from pathlib import Path

from slugify import slugify

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.ingest.diveability import (
    is_osm_non_scuba_diving_tags,
    is_osm_operator_tags,
)
from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.ingest.osm import OVERPASS_ENDPOINTS, _float_or_none
from dive_atlas.ingest.padi import MAP_CAP, _Bounds, _as_depth_m, _country_from_travel_url
from dive_atlas.ingest.type_map import normalize_site_types, osm_tags_to_types
from dive_atlas.schemas import DiveSiteIn, RegionIn
from dive_atlas.services.geo_enrich import COUNTRY_SLUGS, area_for_point
from dive_atlas.taxonomy import SourceKind, WaterType

HOTSPOTS_PATH = Path(__file__).resolve().parents[3] / "data" / "sources" / "dense_hotspots.json"
PADI_LIST = "https://travel.padi.com/api/v2/travel/dive-guide/world/all/dive-sites/"
PADI_MAP = "https://travel.padi.com/api/v2/travel/dsl/dive-sites/map/"


def _load_hotspots(path: Path | None = None) -> list[dict]:
    p = path or HOTSPOTS_PATH
    return list(json.loads(p.read_text(encoding="utf-8")).get("hotspots") or [])


def _scuba_query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"{south},{west},{north},{east}"
    return f"""
    [out:json][timeout:90];
    (
      node["sport"="scuba_diving"]({bbox});
      way["sport"="scuba_diving"]({bbox});
      node["scuba_diving"]({bbox});
      way["scuba_diving"]({bbox});
      node["leisure"="diving"]({bbox});
      node["sport"="diving"]({bbox});
      node["scuba_diving:divespot"="yes"]({bbox});
    );
    out center tags;
    """
    # dive_centre nodes are operators — excluded on purpose.


def _tiles_for_hotspot(hot: dict) -> list[dict]:
    tiles = list(hot.get("subtiles") or [])
    tiles.append(
        {
            "slug": f"{hot['slug']}-full",
            "name": hot["name"],
            "south": hot["south"],
            "west": hot["west"],
            "north": hot["north"],
            "east": hot["east"],
        }
    )
    # Dedupe identical bboxes
    seen: set[tuple[float, float, float, float]] = set()
    out: list[dict] = []
    for t in tiles:
        key = (
            round(float(t["south"]), 4),
            round(float(t["west"]), 4),
            round(float(t["north"]), 4),
            round(float(t["east"]), 4),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


@register_adapter
class DenseHotspotsAdapter(CrawlerAdapter):
    """Fine-tile OSM (+ PADI map pins) crawl for named dive hotspots."""

    slug = "dense-hotspots"
    name = "Dense dive hotspot tiles (OSM + PADI map)"
    kind = SourceKind.OPEN_DATA

    def __init__(
        self,
        *,
        hotspot: str | None = None,
        skip: list[str] | None = None,
        include_padi: bool = True,
        path: Path | None = None,
    ) -> None:
        all_hots = _load_hotspots(path)
        if hotspot:
            wanted = {h.strip().lower() for h in hotspot.split(",") if h.strip()}
            all_hots = [
                h
                for h in all_hots
                if h["slug"] in wanted or h["name"].lower() in wanted
            ]
            if not all_hots:
                known = ", ".join(h["slug"] for h in _load_hotspots(path))
                raise ValueError(f"Unknown hotspot {hotspot!r}. Known: {known}")
        if skip:
            skip_set = {s.strip().lower() for s in skip}
            all_hots = [h for h in all_hots if h["slug"] not in skip_set]
        self.hotspots = all_hots
        self.include_padi = include_padi

    def fetch(self) -> IngestBatch:
        sites: list[DiveSiteIn] = []
        regions: dict[str, RegionIn] = {}
        seen: set[str] = set()
        errors: list[str] = []
        osm_n = padi_n = 0

        with HttpFetcher(min_interval_s=0.9, timeout=100.0) as http:
            # --- OSM fine tiles ---
            for hot in self.hotspots:
                region_slug = f"hotspot-{hot['slug']}"
                regions[region_slug] = RegionIn(
                    slug=region_slug,
                    name=hot["name"],
                    kind="archipelago",
                    country_code=hot.get("country_code"),
                    aliases=[hot["name"], hot["slug"].replace("-", " ")],
                    properties={"source": "dense-hotspots"},
                )
                for tile in _tiles_for_hotspot(hot):
                    try:
                        data = self._overpass(
                            http,
                            float(tile["south"]),
                            float(tile["west"]),
                            float(tile["north"]),
                            float(tile["east"]),
                        )
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"osm:{hot['slug']}/{tile.get('slug')}: {exc}")
                        continue
                    added = 0
                    for el in data.get("elements") or []:
                        site = self._osm_element_to_site(
                            el, hot=hot, tile_name=tile.get("name") or hot["name"]
                        )
                        if site is None:
                            continue
                        key = site.external_id or site.slug or site.name
                        if key in seen:
                            continue
                        seen.add(key)
                        site.region_slug = region_slug
                        sites.append(site)
                        osm_n += 1
                        added += 1
                    print(
                        f"  dense OSM {hot['slug']}/{tile.get('slug')}: +{added} "
                        f"(total={len(sites)})",
                        flush=True,
                    )

            # --- PADI map pins (one world-list join) ---
            if self.include_padi:
                try:
                    padi_sites = self._padi_all_hotspots(http, regions)
                    for site in padi_sites:
                        key = site.external_id or site.slug or site.name
                        if key in seen:
                            continue
                        seen.add(key)
                        sites.append(site)
                        padi_n += 1
                    print(f"  dense PADI joined: +{padi_n} (total={len(sites)})", flush=True)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"padi: {exc}")

        return IngestBatch(
            source_slug=self.slug,
            source_name=self.name,
            source_kind=self.kind,
            regions=list(regions.values()),
            sites=sites,
            meta={
                "hotspots": [h["slug"] for h in self.hotspots],
                "sites": len(sites),
                "osm_sites": osm_n,
                "padi_sites": padi_n,
                "errors": errors,
            },
        )

    def _overpass(
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
                data = resp.json()
                if "elements" in data:
                    return data
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
        if last_err:
            raise last_err
        return {"elements": []}

    def _osm_element_to_site(self, el: dict, *, hot: dict, tile_name: str) -> DiveSiteIn | None:
        tags = el.get("tags") or {}
        if is_osm_operator_tags(tags) or is_osm_non_scuba_diving_tags(tags):
            return None
        if el.get("type") == "way" and "center" in el:
            lat = float(el["center"]["lat"])
            lon = float(el["center"]["lon"])
        elif "lat" in el and "lon" in el:
            lat = float(el["lat"])
            lon = float(el["lon"])
        else:
            return None
        name = tags.get("name") or tags.get("name:en") or f"OSM {el.get('type')}/{el.get('id')}"
        osm_id = f"{el.get('type')}/{el.get('id')}"
        types = osm_tags_to_types(tags)
        area = area_for_point(lat, lon)
        locality = (
            (area.name if area else None)
            or tags.get("addr:city")
            or tile_name
            or hot.get("locality")
            or hot["name"]
        )
        country = (area.country_code if area else None) or hot.get("country_code")
        return DiveSiteIn(
            slug=f"osm-{slugify(osm_id)}-{slugify(name)}"[:240],
            name=name,
            site_types=types,
            water_type=WaterType.SALT.value,
            country_code=country,
            locality=locality,
            description=tags.get("description") or tags.get("note"),
            depth_max_m=_float_or_none(tags.get("depth") or tags.get("maxdepth")),
            lon=lon,
            lat=lat,
            tags=["osm", "dense-hotspot", hot["slug"], slugify(locality), *types],
            confidence=0.75,
            external_id=osm_id,
            external_url=f"https://www.openstreetmap.org/{osm_id}",
            properties={
                "osm_tags": tags,
                "hotspot": hot["slug"],
                "tile": tile_name,
            },
            raw={"type": el.get("type"), "id": el.get("id"), "tags": tags},
        )

    def _padi_all_hotspots(
        self, http: HttpFetcher, regions: dict[str, RegionIn]
    ) -> list[DiveSiteIn]:
        old = http._min_interval
        http._min_interval = 0.1
        # pin_id -> (pin, hotspot)
        owned: dict[int, tuple[dict, dict]] = {}
        for hot in self.hotspots:
            store: dict[int, dict] = {}
            seeds = [
                _Bounds(
                    float(hot["south"]),
                    float(hot["west"]),
                    float(hot["north"]),
                    float(hot["east"]),
                )
            ]
            for tile in hot.get("subtiles") or []:
                seeds.append(
                    _Bounds(
                        float(tile["south"]),
                        float(tile["west"]),
                        float(tile["north"]),
                        float(tile["east"]),
                    )
                )
            for bounds in seeds:
                self._collect_padi(http, bounds, store, min_span=0.2)
            for sid, pin in store.items():
                if sid not in owned:
                    owned[sid] = (pin, hot)
            print(
                f"  dense PADI map {hot['slug']}: pins={len(store)} "
                f"(unique_all={len(owned)})",
                flush=True,
            )

        wanted = set(owned)
        meta: dict[int, dict] = {}
        page = 1
        while wanted - meta.keys():
            data = http.get_json(PADI_LIST, params={"page": page, "page_size": 100})
            for row in data.get("results") or []:
                sid = int(row["id"])
                if sid in wanted:
                    meta[sid] = row
            if not data.get("next"):
                break
            page += 1
            if page > 80:
                break
            if page % 15 == 0:
                print(
                    f"  dense PADI list page={page} matched={len(meta)}/{len(wanted)}",
                    flush=True,
                )
        print(f"  dense PADI meta matched {len(meta)}/{len(wanted)}", flush=True)

        sites: list[DiveSiteIn] = []
        for sid, (pin, hot) in owned.items():
            lat = float(pin["latitude"])
            lon = float(pin["longitude"])
            row = meta.get(sid) or {}
            title = row.get("title") or f"PADI site {sid}"
            travel_url = row.get("travelUrl") or ""
            country_slug = _country_from_travel_url(travel_url)
            country_code = (
                COUNTRY_SLUGS.get(country_slug.lower()) if country_slug else None
            ) or hot.get("country_code")
            area = area_for_point(lat, lon)
            locality = (area.name if area else None) or hot.get("locality") or hot["name"]
            types = normalize_site_types(*(row.get("types") or ["reef"]))
            abs_url = (
                f"https://travel.padi.com{travel_url}"
                if travel_url.startswith("/")
                else travel_url or None
            )
            region_slug = f"hotspot-{hot['slug']}"
            sites.append(
                DiveSiteIn(
                    slug=f"padi-{sid}-{slugify(title)}"[:240],
                    name=title,
                    site_types=types,
                    region_slug=region_slug if region_slug in regions else None,
                    country_code=country_code,
                    locality=locality,
                    depth_max_m=_as_depth_m(row.get("maximumDepth")),
                    lon=lon,
                    lat=lat,
                    tags=["padi", "dense-hotspot", hot["slug"], *types],
                    confidence=0.85 if row else 0.55,
                    external_id=str(sid),
                    external_url=abs_url,
                    properties={
                        "padi_id": sid,
                        "marine_life": row.get("marineLife") or [],
                        "hotspot": hot["slug"],
                        "map_only": not bool(row),
                    },
                    raw={"id": sid, "title": title, "travelUrl": travel_url},
                )
            )
        http._min_interval = old
        return sites

    def _collect_padi(
        self, http: HttpFetcher, bounds: _Bounds, store: dict[int, dict], *, min_span: float
    ) -> None:
        if bounds.span < 1e-4:
            return
        pins = http.get_json(
            PADI_MAP,
            params={
                "bottom_left": f"{bounds.sw_lat},{bounds.sw_lng}",
                "top_right": f"{bounds.ne_lat},{bounds.ne_lng}",
            },
        )
        if not pins:
            return
        if len(pins) < MAP_CAP or bounds.span <= min_span:
            for p in pins:
                store[int(p["id"])] = p
            return
        for child in bounds.split():
            self._collect_padi(http, child, store, min_span=min_span)
