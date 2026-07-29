"""Static dive-site maps: OSM basemap + dive-flag markers."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path

import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Polygon, Rectangle  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

# OpenStreetMap raster tiles (fair-use / attribution required on exports).
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "DiveAtlas/0.1 (https://github.com/nyxtom; research map export)"


@dataclass(frozen=True)
class MapRegion:
    slug: str
    title: str
    south: float
    west: float
    north: float
    east: float
    zoom: int | None = None


PRESET_REGIONS: dict[str, MapRegion] = {
    "roatan": MapRegion(
        "roatan",
        "Roatán — dive sites",
        16.22,
        -86.78,
        16.45,
        -86.38,
        zoom=11,
    ),
    "bay-islands": MapRegion(
        "bay-islands",
        "Bay Islands (Roatán / Utila) — dive sites",
        15.95,
        -87.10,
        16.50,
        -86.30,
        zoom=10,
    ),
    "okinawa": MapRegion(
        "okinawa",
        "Okinawa / Kerama — dive sites",
        25.95,
        127.10,
        26.95,
        128.40,
        zoom=9,
    ),
    "yaeyama": MapRegion(
        "yaeyama",
        "Yaeyama (Ishigaki / Iriomote) — dive sites",
        24.05,
        123.55,
        24.65,
        124.45,
        zoom=10,
    ),
    "japan": MapRegion(
        "japan",
        "Japan — dive sites",
        24.0,
        123.0,
        42.0,
        146.0,
        zoom=5,
    ),
    "izu": MapRegion(
        "izu",
        "Izu Peninsula — dive sites",
        34.55,
        138.65,
        35.15,
        139.25,
        zoom=10,
    ),
}


@dataclass
class SitePin:
    name: str
    lat: float
    lon: float
    site_types: list[str]
    locality: str | None
    source_hint: str | None = None


def _latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    lat_rad = math.radians(lat)
    n = 2.0**zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def _tile_to_latlon(x: float, y: float, zoom: int) -> tuple[float, float]:
    n = 2.0**zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    return math.degrees(lat_rad), lon


def _auto_zoom(south: float, west: float, north: float, east: float, *, max_tiles: int = 12) -> int:
    """Pick a zoom that keeps the mosaic under ~max_tiles on the long side."""
    for z in range(14, 3, -1):
        x0, y0 = _latlon_to_tile(north, west, z)
        x1, y1 = _latlon_to_tile(south, east, z)
        w = abs(x1 - x0) + 1
        h = abs(y1 - y0) + 1
        if max(w, h) <= max_tiles:
            return z
    return 4


def fetch_basemap(
    south: float,
    west: float,
    north: float,
    east: float,
    *,
    zoom: int | None = None,
    pad_tiles: int = 0,
) -> tuple[Image.Image, tuple[float, float, float, float], int]:
    """Return (image, (west,east,south,north) of image extent, zoom)."""
    z = zoom if zoom is not None else _auto_zoom(south, west, north, east)
    x0f, y0f = _latlon_to_tile(north, west, z)
    x1f, y1f = _latlon_to_tile(south, east, z)
    x0, x1 = int(math.floor(min(x0f, x1f))) - pad_tiles, int(math.floor(max(x0f, x1f))) + pad_tiles
    y0, y1 = int(math.floor(min(y0f, y1f))) - pad_tiles, int(math.floor(max(y0f, y1f))) + pad_tiles
    # Clamp tile indices
    n = 2**z
    x0, x1 = max(0, x0), min(n - 1, x1)
    y0, y1 = max(0, y0), min(n - 1, y1)

    tw = th = 256
    mosaic = Image.new("RGB", ((x1 - x0 + 1) * tw, (y1 - y0 + 1) * th), (220, 230, 240))
    with httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT}) as client:
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                url = TILE_URL.format(z=z, x=tx, y=ty)
                try:
                    r = client.get(url)
                    r.raise_for_status()
                    tile = Image.open(io.BytesIO(r.content)).convert("RGB")
                except Exception:
                    tile = Image.new("RGB", (tw, th), (200, 210, 220))
                mosaic.paste(tile, ((tx - x0) * tw, (ty - y0) * th))

    north_ext, west_ext = _tile_to_latlon(x0, y0, z)
    south_ext, east_ext = _tile_to_latlon(x1 + 1, y1 + 1, z)
    return mosaic, (west_ext, east_ext, south_ext, north_ext), z


def _draw_dive_flag(ax, x: float, y: float, *, size: float = 0.018) -> None:
    """Classic scuba dive flag (red field, white diagonal) in axes fraction-ish data coords.

    ``size`` is in data degrees (approx); callers should pass a sensible value for the bbox.
    """
    w, h = size, size * 0.7
    # Red rectangle
    ax.add_patch(
        Rectangle(
            (x - w / 2, y - h / 2),
            w,
            h,
            facecolor="#d62828",
            edgecolor="#1a1a1a",
            linewidth=0.6,
            zorder=5,
            clip_on=True,
        )
    )
    # White diagonal stripe (bottom-left → top-right)
    stripe = np.array(
        [
            [x - w / 2, y - h / 2 + h * 0.15],
            [x - w / 2 + w * 0.25, y - h / 2],
            [x + w / 2, y + h / 2 - h * 0.15],
            [x + w / 2 - w * 0.25, y + h / 2],
        ]
    )
    ax.add_patch(
        Polygon(stripe, closed=True, facecolor="white", edgecolor="none", zorder=6, clip_on=True)
    )


def sites_in_bbox(
    session: Session,
    *,
    south: float,
    west: float,
    north: float,
    east: float,
    limit: int = 2000,
) -> list[SitePin]:
    rows = session.execute(
        text(
            """
            SELECT s.name,
                   ST_Y(s.geom::geometry) AS lat,
                   ST_X(s.geom::geometry) AS lon,
                   s.site_types,
                   s.locality,
                   (
                     SELECT ds.slug FROM source_records sr
                     JOIN data_sources ds ON ds.id = sr.source_id
                     WHERE sr.site_id = s.id
                     ORDER BY ds.slug LIMIT 1
                   ) AS src
            FROM dive_sites s
            WHERE ST_Y(s.geom::geometry) BETWEEN :south AND :north
              AND ST_X(s.geom::geometry) BETWEEN :west AND :east
            ORDER BY s.name
            LIMIT :lim
            """
        ),
        {"south": south, "west": west, "north": north, "east": east, "lim": limit},
    ).fetchall()
    return [
        SitePin(
            name=r.name,
            lat=float(r.lat),
            lon=float(r.lon),
            site_types=list(r.site_types or []),
            locality=r.locality,
            source_hint=r.src,
        )
        for r in rows
    ]


def density_grid(
    pins: list[SitePin],
    *,
    south: float,
    west: float,
    north: float,
    east: float,
    cells: int = 24,
) -> tuple[np.ndarray, list[float], list[float]]:
    """Simple count grid for heatmap overlay."""
    if north <= south or east <= west:
        return np.zeros((cells, cells)), [], []
    lats = np.linspace(south, north, cells + 1)
    lons = np.linspace(west, east, cells + 1)
    grid = np.zeros((cells, cells), dtype=float)
    for p in pins:
        if not (south <= p.lat <= north and west <= p.lon <= east):
            continue
        yi = min(cells - 1, max(0, int((p.lat - south) / (north - south) * cells)))
        xi = min(cells - 1, max(0, int((p.lon - west) / (east - west) * cells)))
        grid[yi, xi] += 1
    return grid, lats.tolist(), lons.tolist()


def render_dive_map(
    pins: list[SitePin],
    *,
    south: float,
    west: float,
    north: float,
    east: float,
    title: str,
    out_path: Path,
    zoom: int | None = None,
    show_labels: bool = False,
    label_limit: int = 18,
    heatmap: bool = True,
    dpi: int = 160,
) -> dict:
    """Render OSM basemap + dive flags (+ optional density wash) to PNG."""
    basemap, extent, z = fetch_basemap(south, west, north, east, zoom=zoom)
    west_e, east_e, south_e, north_e = extent

    fig_w = 11.0
    aspect = basemap.height / max(1, basemap.width)
    fig_h = max(7.0, fig_w * aspect * 0.95)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    ax.imshow(
        basemap,
        extent=[west_e, east_e, south_e, north_e],
        origin="upper",
        aspect="equal",
        zorder=1,
    )
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)

    if heatmap and pins:
        grid, _, _ = density_grid(
            pins, south=south, west=west, north=north, east=east, cells=28
        )
        if grid.max() > 0:
            ax.imshow(
                np.ma.masked_where(grid == 0, grid),
                extent=[west, east, south, north],
                origin="lower",
                cmap="YlOrRd",
                alpha=0.35,
                interpolation="bilinear",
                zorder=2,
                aspect="equal",
            )

    # Flag size scales with map span; overview maps use scatter markers instead.
    span = max(east - west, north - south)
    use_scatter = span > 4.0
    if use_scatter:
        ax.scatter(
            [p.lon for p in pins],
            [p.lat for p in pins],
            s=36,
            c="#d62828",
            edgecolors="white",
            linewidths=0.7,
            marker="o",
            zorder=5,
            label="Dive site",
        )
    else:
        flag_size = max(0.006, min(0.04, span * 0.03))
        for p in pins:
            _draw_dive_flag(ax, p.lon, p.lat, size=flag_size)
        ax.scatter([], [], c="#d62828", marker="s", s=60, label="Dive site")

    if show_labels and pins:
        # Label a spread of sites (avoid stacking + skip non-Latin names without CJK fonts).
        def _labelable(name: str) -> bool:
            return all(ord(ch) < 0x3000 for ch in name)

        labeled = [p for p in pins if _labelable(p.name)]
        step = max(1, len(labeled) // label_limit)
        for i, p in enumerate(labeled[::step][:label_limit]):
            ax.annotate(
                p.name[:28],
                (p.lon, p.lat),
                textcoords="offset points",
                xytext=(6, 4),
                fontsize=6.5,
                color="#111",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75),
                zorder=7,
            )

    ax.set_title(f"{title}  ·  {len(pins)} sites", fontsize=14, pad=10, fontweight="bold")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.text(
        0.01,
        0.01,
        "Basemap © OpenStreetMap  ·  Dive Atlas",
        transform=ax.transAxes,
        fontsize=7,
        color="#333",
        alpha=0.85,
        zorder=8,
    )
    ax.legend(loc="upper right", framealpha=0.9, fontsize=8)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return {
        "path": str(out_path),
        "sites": len(pins),
        "zoom": z,
        "bbox": [south, west, north, east],
        "title": title,
    }


def render_preset(
    session: Session,
    region_slug: str,
    *,
    out_dir: Path,
    show_labels: bool = True,
    heatmap: bool = True,
) -> dict:
    if region_slug not in PRESET_REGIONS:
        known = ", ".join(sorted(PRESET_REGIONS))
        raise ValueError(f"Unknown region {region_slug!r}. Presets: {known}")
    reg = PRESET_REGIONS[region_slug]
    pins = sites_in_bbox(
        session,
        south=reg.south,
        west=reg.west,
        north=reg.north,
        east=reg.east,
    )
    out = Path(out_dir) / f"dive-map-{reg.slug}.png"
    return render_dive_map(
        pins,
        south=reg.south,
        west=reg.west,
        north=reg.north,
        east=reg.east,
        title=reg.title,
        out_path=out,
        zoom=reg.zoom,
        show_labels=show_labels and len(pins) <= 80,
        heatmap=heatmap,
    )
