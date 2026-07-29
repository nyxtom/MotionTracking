"""Registry-driven harvest of operator / marine-park dive maps (KML, GPX, GeoJSON).

Worldwide operator maps are not one API — they are thousands of shop Google My Maps,
marine-park mooring files, and resort site lists. This adapter reads a curated
registry (`data/sources/operator_maps.json`) and normalizes each entry into sites.

Growth strategy:
1. OpenDiveMap / PADI / OSM — bulk baselines (separate adapters)
2. Official marine-park KML/GPX (high trust) — add to this registry
3. Public Google My Maps from shops/parks (`format: google_my_maps` + `mid`)
4. Later: crawl known operator websites for embedded map IDs
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from slugify import slugify

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.ingest.geo_files import GeoPoint, parse_bytes
from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.ingest.type_map import normalize_site_types
from dive_atlas.schemas import DiveSiteIn
from dive_atlas.services.geo_enrich import area_for_point, country_bbox_for_point
from dive_atlas.taxonomy import SourceKind, WaterType

REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "sources" / "operator_maps.json"
)

GOOGLE_KML = "https://www.google.com/maps/d/kml?mid={mid}&forcekml=1"


def load_operator_map_registry(path: Path | None = None) -> list[dict]:
    p = path or REGISTRY_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    return list(data.get("maps") or [])


@register_adapter
class OperatorMapsAdapter(CrawlerAdapter):
    """Fetch curated operator / marine-park map files into dive sites."""

    slug = "operator-maps"
    name = "Operator & marine-park dive maps"
    kind = SourceKind.OPEN_DATA

    def __init__(
        self,
        *,
        only: str | None = None,
        path: Path | None = None,
        status: str = "active",
    ) -> None:
        maps = load_operator_map_registry(path)
        if only:
            wanted = {s.strip().lower() for s in only.split(",") if s.strip()}
            maps = [m for m in maps if m.get("slug", "").lower() in wanted]
        if status:
            maps = [m for m in maps if (m.get("status") or "active") == status]
        self.maps = maps

    def fetch(self) -> IngestBatch:
        sites: list[DiveSiteIn] = []
        errors: list[str] = []
        with HttpFetcher(
            min_interval_s=0.4,
            timeout=90.0,
            headers={"User-Agent": "DiveAtlas/0.1 (https://github.com/nyxtom; research)"},
        ) as http:
            for entry in self.maps:
                try:
                    points = self._fetch_entry(http, entry)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{entry.get('slug')}: {exc}")
                    continue
                for pt in points:
                    site = self._point_to_site(pt, entry)
                    if site:
                        sites.append(site)
                print(
                    f"  operator-map {entry.get('slug')}: +{len(points)} "
                    f"(total={len(sites)})",
                    flush=True,
                )
        return IngestBatch(
            source_slug=self.slug,
            source_name=self.name,
            source_kind=self.kind,
            sites=sites,
            meta={
                "maps": [m.get("slug") for m in self.maps],
                "sites": len(sites),
                "errors": errors,
            },
        )

    def _fetch_entry(self, http: HttpFetcher, entry: dict) -> list[GeoPoint]:
        fmt = (entry.get("format") or "").lower()
        if fmt == "google_my_maps":
            mid = entry.get("mid") or entry.get("google_mid")
            if not mid:
                raise ValueError("google_my_maps entry needs mid")
            raw = http.get_bytes(GOOGLE_KML.format(mid=mid))
            return parse_bytes(raw, fmt="kml")

        url = entry.get("url")
        if not url:
            raise ValueError(f"{entry.get('slug')} missing url")
        raw = http.get_bytes(url)
        file_fmt = fmt or _guess_fmt(url)
        return parse_bytes(raw, fmt=file_fmt)

    def _point_to_site(self, pt: GeoPoint, entry: dict) -> DiveSiteIn | None:
        if not (-90 <= pt.lat <= 90 and -180 <= pt.lon <= 180):
            return None
        types = normalize_site_types(*(entry.get("default_types") or ["reef"]))
        blob = pt.name.lower()
        if "wreck" in blob or "ship" in blob:
            types = normalize_site_types("wreck", *types)
        if "cave" in blob or "cavern" in blob:
            types = normalize_site_types("cave", *types)
        if "wall" in blob:
            types = normalize_site_types("wall", *types)

        area = area_for_point(pt.lat, pt.lon)
        country = entry.get("country_code") or (area.country_code if area else None)
        locality = entry.get("locality") or (area.name if area else None)
        if not country:
            bbox = country_bbox_for_point(pt.lat, pt.lon)
            if bbox:
                country = bbox.country_code

        conf = float(entry.get("confidence") or 0.8)
        slug_base = entry.get("slug") or "opmap"
        digest = hashlib.sha1(
            f"{pt.lon:.5f}:{pt.lat:.5f}:{pt.name}".encode()
        ).hexdigest()[:10]
        display = pt.name.title() if pt.name.isupper() else pt.name
        return DiveSiteIn(
            slug=f"opmap-{slug_base}-{slugify(display)}-{digest}"[:240],
            name=display,
            site_types=types,
            water_type=WaterType.SALT.value,
            country_code=country,
            locality=locality,
            description=pt.description,
            lon=pt.lon,
            lat=pt.lat,
            tags=["operator-map", slug_base, *(entry.get("tags") or [])],
            confidence=conf,
            external_id=digest,
            external_url=entry.get("page_url") or entry.get("url"),
            properties={
                "operator_map_slug": slug_base,
                "operator_name": entry.get("operator") or entry.get("name"),
                "map_format": entry.get("format"),
                "source_kind": entry.get("kind") or "operator",
            },
            raw={"entry": {k: entry.get(k) for k in ("slug", "name", "format", "mid", "url")}},
        )


def _guess_fmt(url: str) -> str:
    u = url.lower().split("?")[0]
    for ext in ("geojson", "json", "kml", "kmz", "gpx"):
        if u.endswith("." + ext):
            return "geojson" if ext == "json" else ext
    return "geojson"
