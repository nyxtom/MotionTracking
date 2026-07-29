"""OpenDiveMap open API — community GeoJSON dive sites (no auth)."""

from __future__ import annotations

from slugify import slugify

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.ingest.type_map import normalize_site_types
from dive_atlas.schemas import DiveSiteIn
from dive_atlas.services.geo_enrich import area_for_point, country_bbox_for_point
from dive_atlas.taxonomy import SourceKind, WaterType

API = "https://api.opendivemap.com/v1/sites"


@register_adapter
class OpenDiveMapAdapter(CrawlerAdapter):
    """Bulk pull from OpenDiveMap (https://opendivemap.com) — open GeoJSON API."""

    slug = "opendivemap"
    name = "OpenDiveMap community sites"
    kind = SourceKind.OPEN_DATA

    def __init__(self, *, country: str | None = None, page_size: int = 1000) -> None:
        self.country = country
        self.page_size = min(page_size, 1000)

    def fetch(self) -> IngestBatch:
        sites: list[DiveSiteIn] = []
        with HttpFetcher(
            min_interval_s=0.2,
            headers={"User-Agent": "DiveAtlas/0.1 (https://github.com/nyxtom; research)"},
        ) as http:
            offset = 0
            matched = None
            while True:
                params: dict = {"limit": self.page_size, "offset": offset}
                if self.country:
                    params["country"] = self.country.upper()
                data = http.get_json(API, params=params)
                if matched is None:
                    matched = int(data.get("numberMatched") or 0)
                features = data.get("features") or []
                if not features:
                    break
                for feat in features:
                    site = self._feature_to_site(feat)
                    if site:
                        sites.append(site)
                offset += len(features)
                if offset >= matched or len(features) < self.page_size:
                    break
        return IngestBatch(
            source_slug=self.slug,
            source_name=self.name,
            source_kind=self.kind,
            sites=sites,
            meta={"sites": len(sites), "number_matched": matched},
        )

    def _feature_to_site(self, feat: dict) -> DiveSiteIn | None:
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        if geom.get("type") != "Point":
            return None
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            return None
        lon, lat = float(coords[0]), float(coords[1])
        name = (props.get("name") or "").strip()
        if not name:
            return None
        ext_id = str(props.get("id") or f"{lon:.5f}_{lat:.5f}")
        topologies = props.get("topologies") or []
        types = normalize_site_types(*(topologies if isinstance(topologies, list) else []))
        country = props.get("country_code")
        locality = props.get("sea_name") or props.get("country_name")
        area = area_for_point(lat, lon)
        if area:
            country = country or area.country_code
            locality = area.name or locality
        if not country:
            bbox = country_bbox_for_point(lat, lon)
            if bbox:
                country = bbox.country_code
        entry = (props.get("entry") or "unknown").lower()
        water = WaterType.SALT.value
        env = (props.get("environment") or "").lower()
        if env in {"lake", "river", "spring", "quarry", "pool"}:
            water = WaterType.FRESH.value
        return DiveSiteIn(
            slug=f"odm-{ext_id}-{slugify(name)}"[:240],
            name=name,
            site_types=types,
            water_type=water,
            entry_type=entry if entry in {"shore", "boat"} else "unknown",
            country_code=country,
            locality=locality,
            depth_max_m=props.get("max_depth"),
            lon=lon,
            lat=lat,
            tags=["opendivemap", *(topologies if isinstance(topologies, list) else [])],
            confidence=0.72,
            external_id=ext_id,
            external_url=f"https://opendivemap.com/sites/{ext_id}",
            properties={
                "opendivemap_id": ext_id,
                "sea_mrgid": props.get("sea_mrgid"),
                "tags": props.get("tags") or {},
            },
            raw=feat,
        )
