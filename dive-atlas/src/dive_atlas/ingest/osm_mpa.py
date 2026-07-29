"""OSM marine protected areas / national parks → atlas regions."""

from __future__ import annotations

from slugify import slugify

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.ingest.osm import OVERPASS_ENDPOINTS, REGIONS
from dive_atlas.schemas import RegionIn
from dive_atlas.taxonomy import SourceKind


def _mpa_query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"{south},{west},{north},{east}"
    return f"""
    [out:json][timeout:75];
    (
      relation["boundary"="protected_area"]({bbox});
      relation["boundary"="national_park"]({bbox});
      way["boundary"="protected_area"]({bbox});
      way["boundary"="national_park"]({bbox});
      relation["protect_class"]({bbox});
    );
    out center tags;
    """


@register_adapter
class OsmMpaAdapter(CrawlerAdapter):
    """Coastal protected areas from OSM as atlas regions (MPA / park)."""

    slug = "osm-mpa"
    name = "OSM marine / protected areas"
    kind = SourceKind.OPEN_DATA

    def __init__(self, *, regions: list[tuple[str, float, float, float, float]] | None = None) -> None:
        self.regions = regions or REGIONS

    def fetch(self) -> IngestBatch:
        regions: dict[str, RegionIn] = {}
        errors: list[str] = []
        with HttpFetcher(min_interval_s=1.0, timeout=100.0) as http:
            for tile, south, west, north, east in self.regions:
                try:
                    data = self._query(http, south, west, north, east)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{tile}: {exc}")
                    continue
                added = 0
                for el in data.get("elements") or []:
                    reg = self._element_to_region(el)
                    if reg is None or reg.slug in regions:
                        continue
                    regions[reg.slug] = reg
                    added += 1
                print(
                    f"  osm-mpa {tile}: +{added} (total={len(regions)})",
                    flush=True,
                )
        return IngestBatch(
            source_slug=self.slug,
            source_name=self.name,
            source_kind=self.kind,
            regions=list(regions.values()),
            meta={"regions": len(regions), "errors": errors},
        )

    def _query(
        self, http: HttpFetcher, south: float, west: float, north: float, east: float
    ) -> dict:
        query = _mpa_query(south, west, north, east)
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

    def _element_to_region(self, el: dict) -> RegionIn | None:
        tags = el.get("tags") or {}
        name = (tags.get("name:en") or tags.get("name") or "").strip()
        if not name:
            return None
        osm_id = f"{el.get('type')}/{el.get('id')}"
        kind = "mpa"
        if tags.get("boundary") == "national_park":
            kind = "national_park"
        elif tags.get("protect_class") in {"1", "1a", "1b", "2"}:
            kind = "mpa"
        country = None
        # ISO3166-1 sometimes present
        iso = tags.get("ISO3166-1") or tags.get("country_code")
        if iso and len(iso) == 2:
            country = iso.upper()
        return RegionIn(
            slug=f"osm-mpa-{slugify(osm_id)}-{slugify(name)}"[:200],
            name=name,
            kind=kind,
            country_code=country,
            description=tags.get("description") or tags.get("protection_title"),
            aliases=[a for a in (tags.get("alt_name"), tags.get("short_name")) if a],
            properties={
                "osm_id": osm_id,
                "protect_class": tags.get("protect_class"),
                "boundary": tags.get("boundary"),
                "marine": tags.get("marine"),
                "osm_tags": tags,
                "source": "osm-mpa",
            },
        )
