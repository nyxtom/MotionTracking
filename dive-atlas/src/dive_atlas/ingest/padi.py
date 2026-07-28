from __future__ import annotations

import re
from dataclasses import dataclass, field

from slugify import slugify

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.ingest.type_map import normalize_site_types
from dive_atlas.schemas import DiveSiteIn, RegionIn
from dive_atlas.taxonomy import SourceKind

BASE = "https://travel.padi.com/api/v2/travel"
MAP_CAP = 200
LIST_PAGE_SIZE = 100


@dataclass
class _Bounds:
    sw_lat: float
    sw_lng: float
    ne_lat: float
    ne_lng: float

    def split(self) -> list[_Bounds]:
        mid_lat = (self.sw_lat + self.ne_lat) / 2
        mid_lng = (self.sw_lng + self.ne_lng) / 2
        return [
            _Bounds(self.sw_lat, self.sw_lng, mid_lat, mid_lng),
            _Bounds(self.sw_lat, mid_lng, mid_lat, self.ne_lng),
            _Bounds(mid_lat, self.sw_lng, self.ne_lat, mid_lng),
            _Bounds(mid_lat, mid_lng, self.ne_lat, self.ne_lng),
        ]

    @property
    def span(self) -> float:
        return max(self.ne_lat - self.sw_lat, self.ne_lng - self.sw_lng)


@dataclass
class _PinStore:
    pins: dict[int, dict] = field(default_factory=dict)
    requests: int = 0


def _country_from_travel_url(travel_url: str | None) -> str | None:
    if not travel_url:
        return None
    parts = [p for p in travel_url.strip("/").split("/") if p]
    if len(parts) >= 2 and parts[0] in {"dive-site", "dive-sites"}:
        return parts[1]
    return None


def _as_depth_m(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("m", "").strip())
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in ("meters", "m", "max", "maximum", "value", "depth"):
            if key in value:
                return _as_depth_m(value[key])
    return None


@register_adapter
class PadiTravelAdapter(CrawlerAdapter):
    """Full PADI Travel dive-site catalog (~5k) via public travel API."""

    slug = "padi-travel"
    name = "PADI Travel dive sites"
    kind = SourceKind.TRAVEL_SITE

    _HTML_POINT_RE = re.compile(r"window\.dsPoint\s*=\s*\[\s*\{(.*?)\}\s*\]", re.S)
    _HTML_FIELD_RE = re.compile(r"(id|title|latitude|longitude)\s*:\s*['\"]([^'\"]+)['\"]")

    def __init__(
        self,
        *,
        max_pages: int | None = None,
        min_tile_span: float = 0.5,
        html_backfill_limit: int = 0,
    ) -> None:
        self.max_pages = max_pages
        self.min_tile_span = min_tile_span
        self.html_backfill_limit = html_backfill_limit

    def fetch(self) -> IngestBatch:
        with HttpFetcher(min_interval_s=0.12) as http:
            meta = self._fetch_list(http)
            pins = self._fetch_all_pins(http)
            missing_ids = [sid for sid in meta if sid not in pins][: self.html_backfill_limit]
            if missing_ids:
                pins.update(self._backfill_pins_from_html(http, meta, missing_ids))

        sites: list[DiveSiteIn] = []
        regions: dict[str, RegionIn] = {}
        missing_coords = 0
        for site_id, meta_row in meta.items():
            pin = pins.get(site_id)
            if not pin:
                missing_coords += 1
                continue
            lon = float(pin["longitude"])
            lat = float(pin["latitude"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                missing_coords += 1
                continue
            title = meta_row.get("title") or f"PADI site {site_id}"
            travel_url = meta_row.get("travelUrl") or ""
            country_slug = _country_from_travel_url(travel_url)
            region_slug = None
            if country_slug:
                region_slug = f"padi-{slugify(country_slug)}"
                if region_slug not in regions:
                    regions[region_slug] = RegionIn(
                        slug=region_slug,
                        name=country_slug.replace("-", " ").title(),
                        kind="country",
                        aliases=[country_slug],
                        properties={"source": "padi-travel"},
                    )
            types = normalize_site_types(*(meta_row.get("types") or []))
            depth_m = _as_depth_m(meta_row.get("maximumDepth"))
            abs_url = (
                f"https://travel.padi.com{travel_url}"
                if travel_url.startswith("/")
                else travel_url or None
            )
            sites.append(
                DiveSiteIn(
                    slug=f"padi-{site_id}-{slugify(title)}"[:240],
                    name=title,
                    site_types=types,
                    region_slug=region_slug,
                    locality=country_slug.replace("-", " ").title() if country_slug else None,
                    depth_max_m=depth_m,
                    lon=lon,
                    lat=lat,
                    tags=["padi", "padi-travel", *types],
                    confidence=0.85,
                    external_id=str(site_id),
                    external_url=abs_url,
                    properties={
                        "padi_id": site_id,
                        "marine_life": meta_row.get("marineLife") or [],
                        "image_count": len(meta_row.get("images") or []),
                    },
                    raw={
                        k: meta_row.get(k)
                        for k in ("id", "title", "types", "travelUrl", "maximumDepth")
                    },
                )
            )
        return IngestBatch(
            source_slug=self.slug,
            source_name=self.name,
            source_kind=self.kind,
            regions=list(regions.values()),
            sites=sites,
            meta={
                "list_count": len(meta),
                "pin_count": len(pins),
                "ingested": len(sites),
                "missing_coords": missing_coords,
            },
        )

    def _fetch_list(self, http: HttpFetcher) -> dict[int, dict]:
        out: dict[int, dict] = {}
        page = 1
        while True:
            if self.max_pages is not None and page > self.max_pages:
                break
            data = http.get_json(
                f"{BASE}/dive-guide/world/all/dive-sites/",
                params={"page": page, "page_size": LIST_PAGE_SIZE},
            )
            for row in data.get("results") or []:
                out[int(row["id"])] = row
            if not data.get("next"):
                break
            page += 1
        return out

    def _fetch_pins(self, http: HttpFetcher, bounds: _Bounds) -> list[dict]:
        return http.get_json(
            f"{BASE}/dsl/dive-sites/map/",
            params={
                "bottom_left": f"{bounds.sw_lat},{bounds.sw_lng}",
                "top_right": f"{bounds.ne_lat},{bounds.ne_lng}",
            },
        )

    def _fetch_all_pins(self, http: HttpFetcher) -> dict[int, dict]:
        store = _PinStore()
        seeds: list[_Bounds] = []
        for lat in range(-50, 60, 10):
            for lng in range(-180, 180, 10):
                seeds.append(_Bounds(float(lat), float(lng), float(lat + 10), float(lng + 10)))
        for i, bounds in enumerate(seeds, start=1):
            self._collect_pins(http, bounds, store)
            if i % 36 == 0:
                # ~one latitude band
                print(f"  padi map tiles: band done ({i}/{len(seeds)}), pins={len(store.pins)} req={store.requests}", flush=True)
        print(f"  padi map complete: pins={len(store.pins)} req={store.requests}", flush=True)
        return store.pins

    def _collect_pins(self, http: HttpFetcher, bounds: _Bounds, store: _PinStore) -> None:
        if bounds.span < 1e-4:
            return
        pins = self._fetch_pins(http, bounds)
        store.requests += 1
        if len(pins) == 0:
            return
        if len(pins) < MAP_CAP or bounds.span <= self.min_tile_span:
            for p in pins:
                store.pins[int(p["id"])] = p
            return
        for child in bounds.split():
            self._collect_pins(http, child, store)

    def _backfill_pins_from_html(
        self,
        http: HttpFetcher,
        meta: dict[int, dict],
        missing_ids: list[int],
    ) -> dict[int, dict]:
        found: dict[int, dict] = {}
        http._client.headers["Accept"] = "text/html,application/xhtml+xml"
        for site_id in missing_ids:
            row = meta.get(site_id) or {}
            travel_url = row.get("travelUrl")
            if not travel_url:
                continue
            url = (
                f"https://travel.padi.com{travel_url}"
                if travel_url.startswith("/")
                else travel_url
            )
            try:
                html = http.get_text(url)
            except Exception:  # noqa: BLE001
                continue
            m = self._HTML_POINT_RE.search(html)
            if not m:
                continue
            fields = dict(self._HTML_FIELD_RE.findall(m.group(1)))
            try:
                lat = float(fields["latitude"])
                lon = float(fields["longitude"])
            except (KeyError, ValueError):
                continue
            found[site_id] = {"id": site_id, "latitude": lat, "longitude": lon}
        http._client.headers["Accept"] = "application/json,text/plain,*/*"
        return found
