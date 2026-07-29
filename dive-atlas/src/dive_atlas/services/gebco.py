"""GEBCO bathymetry enrichment via OpenTopoData (gebco2020).

Samples elevation at each dive site. Negative elevation → depth_m = -elev
(underwater). Positive → land / intertidal (stored in properties only).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.models import DiveSite

OPENTOPO = "https://api.opentopodata.org/v1/gebco2020"
BATCH = 100  # OpenTopoData free-tier max locations per request


@dataclass
class GebcoStats:
    scanned: int = 0
    updated: int = 0
    underwater: int = 0
    land: int = 0
    errors: list[str] = field(default_factory=list)


def enrich_sites_gebco(
    session: Session,
    *,
    limit: int | None = None,
    only_missing: bool = True,
    min_interval_s: float = 1.05,
) -> GebcoStats:
    """Write properties.gebco_elevation_m / gebco_depth_m; fill depth_max_m when empty."""
    stats = GebcoStats()
    stmt = select(DiveSite).where(DiveSite.geom.is_not(None)).order_by(DiveSite.id)
    if only_missing:
        stmt = stmt.where(
            text(
                "(properties->>'gebco_elevation_m') IS NULL "
                "AND (properties->>'gebco_depth_m') IS NULL"
            )
        )
    if limit:
        stmt = stmt.limit(limit)
    sites = list(session.scalars(stmt).all())
    stats.scanned = len(sites)
    if not sites:
        return stats

    with HttpFetcher(
        min_interval_s=min_interval_s,
        timeout=60.0,
        headers={"User-Agent": "DiveAtlas/0.1 (https://github.com/nyxtom; research)"},
    ) as http:
        for i in range(0, len(sites), BATCH):
            chunk = sites[i : i + BATCH]
            # Need lon/lat from geom
            locs: list[tuple[DiveSite, float, float]] = []
            for site in chunk:
                row = session.execute(
                    text(
                        "SELECT ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon "
                        "FROM dive_sites WHERE id = :id"
                    ),
                    {"id": site.id},
                ).mappings().first()
                if not row:
                    continue
                locs.append((site, float(row["lat"]), float(row["lon"])))
            if not locs:
                continue
            loc_param = "|".join(f"{lat},{lon}" for _, lat, lon in locs)
            try:
                data = http.get_json(OPENTOPO, params={"locations": loc_param})
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(str(exc))
                continue
            results = data.get("results") or []
            for (site, _lat, _lon), res in zip(locs, results, strict=False):
                elev = res.get("elevation")
                if elev is None:
                    continue
                try:
                    elev_f = float(elev)
                except (TypeError, ValueError):
                    continue
                props = dict(site.properties or {})
                props["gebco_elevation_m"] = elev_f
                props["gebco_dataset"] = res.get("dataset") or "gebco2020"
                if elev_f < 0:
                    depth = -elev_f
                    props["gebco_depth_m"] = depth
                    stats.underwater += 1
                    if site.depth_max_m is None:
                        site.depth_max_m = depth
                else:
                    props["gebco_on_land_m"] = elev_f
                    stats.land += 1
                site.properties = props
                if "gebco" not in (site.tags or []):
                    site.tags = [*(site.tags or []), "gebco"]
                stats.updated += 1
            session.flush()
            print(
                f"  gebco {i + len(locs)}/{len(sites)} updated={stats.updated} "
                f"uw={stats.underwater} land={stats.land}",
                flush=True,
            )
    return stats
