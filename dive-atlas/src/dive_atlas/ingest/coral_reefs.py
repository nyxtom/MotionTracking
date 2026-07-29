"""Global coral reef points — UNEP/WRI Resource Watch + cold-water corals.

Allen Coral Atlas (5 m habitat) is GEE-backed; until Earth Engine creds are
available we ingest the open WRI coral reef location centroids + cold-water
coral points as atlas sites tagged coral-atlas / reef-habitat.
"""

from __future__ import annotations

from slugify import slugify

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.ingest.type_map import normalize_site_types
from dive_atlas.schemas import DiveSiteIn
from dive_atlas.services.geo_enrich import area_for_point, country_bbox_for_point
from dive_atlas.taxonomy import SourceKind, WaterType

RW_QUERY = "https://api.resourcewatch.org/v1/query/{dataset_id}"

# WRI Resource Watch datasets (Carto-backed, public SQL)
SHALLOW_CORAL_DS = "1d23838e-40da-4cf3-b61c-56258d3a5c56"
SHALLOW_TABLE = "bio_004a_coral_reef_locations_edit"
COLD_CORAL_DS = "1bc94710-d7ec-46f9-aa27-edddd87b1625"
COLD_TABLE = "bio_033_cold_water_corals_pts"

PAGE = 500


@register_adapter
class CoralReefsAdapter(CrawlerAdapter):
    """Global coral reef centroids + cold-water coral points (Resource Watch)."""

    slug = "coral-reefs"
    name = "Global coral reefs (WRI / UNEP Resource Watch)"
    kind = SourceKind.OPEN_DATA

    def __init__(self, *, include_cold: bool = True, include_shallow: bool = True) -> None:
        self.include_cold = include_cold
        self.include_shallow = include_shallow

    def fetch(self) -> IngestBatch:
        sites: list[DiveSiteIn] = []
        with HttpFetcher(
            min_interval_s=0.35,
            timeout=90.0,
            headers={"User-Agent": "DiveAtlas/0.1 (https://github.com/nyxtom; research)"},
        ) as http:
            if self.include_shallow:
                sites.extend(self._fetch_shallow(http))
            if self.include_cold:
                sites.extend(self._fetch_cold(http))
        return IngestBatch(
            source_slug=self.slug,
            source_name=self.name,
            source_kind=self.kind,
            sites=sites,
            meta={"sites": len(sites)},
        )

    def _fetch_shallow(self, http: HttpFetcher) -> list[DiveSiteIn]:
        out: list[DiveSiteIn] = []
        offset = 0
        while True:
            sql = (
                f"SELECT cartodb_id, name, orig_name, iso3, parent_iso, "
                f"ST_X(ST_Centroid(the_geom)) AS lon, "
                f"ST_Y(ST_Centroid(the_geom)) AS lat, "
                f"gis_area_k, protect_st "
                f"FROM {SHALLOW_TABLE} "
                f"WHERE the_geom IS NOT NULL "
                f"ORDER BY cartodb_id "
                f"LIMIT {PAGE} OFFSET {offset}"
            )
            data = http.get_json(RW_QUERY.format(dataset_id=SHALLOW_CORAL_DS), params={"sql": sql})
            rows = data.get("data") or []
            if not rows:
                break
            for row in rows:
                site = self._row_to_site(row, kind="shallow_coral")
                if site:
                    out.append(site)
            print(f"  coral shallow offset={offset} +{len(rows)} (total={len(out)})", flush=True)
            offset += len(rows)
            if len(rows) < PAGE:
                break
        return out

    def _fetch_cold(self, http: HttpFetcher) -> list[DiveSiteIn]:
        out: list[DiveSiteIn] = []
        offset = 0
        while True:
            sql = (
                f"SELECT cartodb_id, unique_id, start_lati AS lat, start_long AS lon, "
                f"status_of_, determiner "
                f"FROM {COLD_TABLE} "
                f"WHERE start_lati IS NOT NULL AND start_long IS NOT NULL "
                f"ORDER BY cartodb_id "
                f"LIMIT {PAGE} OFFSET {offset}"
            )
            data = http.get_json(RW_QUERY.format(dataset_id=COLD_CORAL_DS), params={"sql": sql})
            rows = data.get("data") or []
            if not rows:
                break
            for row in rows:
                lat, lon = row.get("lat"), row.get("lon")
                if lat is None or lon is None:
                    continue
                try:
                    lat_f, lon_f = float(lat), float(lon)
                except (TypeError, ValueError):
                    continue
                if lat_f == 0 and lon_f == 0:
                    continue
                uid = row.get("unique_id") or row.get("cartodb_id")
                name = f"Cold-water coral {uid}"
                area = area_for_point(lat_f, lon_f)
                country = area.country_code if area else None
                locality = area.name if area else None
                if not country:
                    bbox = country_bbox_for_point(lat_f, lon_f)
                    if bbox:
                        country = bbox.country_code
                out.append(
                    DiveSiteIn(
                        slug=f"coral-cold-{uid}-{slugify(str(uid))}"[:240],
                        name=name,
                        site_types=normalize_site_types("reef"),
                        water_type=WaterType.SALT.value,
                        country_code=country,
                        locality=locality,
                        lon=lon_f,
                        lat=lat_f,
                        tags=["coral-reefs", "cold-water-coral", "resource-watch"],
                        confidence=0.55,
                        external_id=str(uid),
                        external_url="https://resourcewatch.org/",
                        properties={
                            "coral_kind": "cold_water",
                            "status": row.get("status_of_"),
                            "determiner": row.get("determiner"),
                        },
                        raw=row,
                    )
                )
            print(f"  coral cold offset={offset} +{len(rows)} (total={len(out)})", flush=True)
            offset += len(rows)
            if len(rows) < PAGE:
                break
        return out

    def _row_to_site(self, row: dict, *, kind: str) -> DiveSiteIn | None:
        lon, lat = row.get("lon"), row.get("lat")
        if lon is None or lat is None:
            return None
        try:
            lon_f, lat_f = float(lon), float(lat)
        except (TypeError, ValueError):
            return None
        if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
            return None
        name = (row.get("name") or row.get("orig_name") or "").strip()
        cid = row.get("cartodb_id")
        if not name:
            name = f"Coral reef {cid}"
        iso = (row.get("iso3") or row.get("parent_iso") or "")[:3].upper() or None
        area = area_for_point(lat_f, lon_f)
        country = area.country_code if area else None
        locality = area.name if area else None
        if not country:
            bbox = country_bbox_for_point(lat_f, lon_f)
            if bbox:
                country = bbox.country_code
        return DiveSiteIn(
            slug=f"coral-shallow-{cid}-{slugify(name)}"[:240],
            name=name,
            site_types=normalize_site_types("reef"),
            water_type=WaterType.SALT.value,
            country_code=country,
            locality=locality,
            lon=lon_f,
            lat=lat_f,
            tags=["coral-reefs", "shallow-coral", "resource-watch", "allen-coral-proxy"],
            confidence=0.6,
            external_id=str(cid),
            external_url="https://resourcewatch.org/data/explore/bio044a-Coral-Reef-Locations",
            properties={
                "coral_kind": kind,
                "iso3": iso,
                "gis_area_km2": row.get("gis_area_k"),
                "protect_status": row.get("protect_st"),
                "note": "Centroid of UNEP-WCMC/WRI coral reef polygon; Allen Coral Atlas GEE layer pending credentials",
            },
            raw=row,
        )
