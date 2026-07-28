from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select, text

from dive_atlas import __version__
from dive_atlas.db import ensure_extensions, get_engine, session_scope
from dive_atlas.ingest import get_adapter, list_adapters, load_all_adapters
from dive_atlas.models import Base, DiveSite, Operator, Region
from dive_atlas.services.ingest import ingest_batch
from dive_atlas.services.search import search_sites

app = typer.Typer(
    name="dive-atlas",
    help="Global dive site atlas — PostGIS knowledge graph (no website required).",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main() -> None:
    """Dive Atlas CLI."""


@app.command("version")
def version_cmd() -> None:
    console.print(f"dive-atlas {__version__}")


@app.command("init-db")
def init_db() -> None:
    """Create PostGIS extensions and all tables."""
    engine = get_engine()
    ensure_extensions(engine)
    Base.metadata.create_all(engine)
    console.print("[green]Database initialized[/green] (extensions + tables).")


@app.command("adapters")
def adapters_cmd() -> None:
    """List registered crawler adapters."""
    load_all_adapters()
    for slug in list_adapters():
        adapter = get_adapter(slug)
        console.print(f"[bold]{slug}[/bold]  ({adapter.kind.value}) — {adapter.name}")


@app.command("ingest")
def ingest_cmd(
    adapter: str = typer.Argument(..., help="Adapter slug, e.g. seed-famous"),
) -> None:
    """Run a crawler adapter and upsert into PostGIS."""
    load_all_adapters()
    batch = get_adapter(adapter).fetch()
    with session_scope() as session:
        stats = ingest_batch(session, batch)
    console.print(
        f"[green]Ingested[/green] {stats['regions']} regions, {stats['sites']} sites "
        f"from [bold]{adapter}[/bold]."
    )


@app.command("search")
def search_cmd(
    q: Optional[str] = typer.Option(None, "--q", "-q", help="Name / locality text"),
    site_type: Optional[str] = typer.Option(None, "--type", "-t", help="Site type filter"),
    country: Optional[str] = typer.Option(None, "--country", "-c", help="ISO country code"),
    near: Optional[str] = typer.Option(
        None, "--near", help="lon,lat for radius search (e.g. -87.45,20.32)"
    ),
    radius_km: float = typer.Option(50.0, "--radius-km", help="Radius for --near"),
    limit: int = typer.Option(25, "--limit", "-n"),
) -> None:
    """Search the atlas."""
    near_lon = near_lat = None
    if near:
        parts = near.split(",")
        if len(parts) != 2:
            raise typer.BadParameter("--near must be lon,lat")
        near_lon, near_lat = float(parts[0]), float(parts[1])

    with session_scope() as session:
        results = search_sites(
            session,
            q=q,
            site_type=site_type,
            country_code=country,
            near_lon=near_lon,
            near_lat=near_lat,
            radius_m=radius_km * 1000,
            limit=limit,
        )

    table = Table(title="Dive sites")
    table.add_column("Name")
    table.add_column("Types")
    table.add_column("Country")
    table.add_column("Locality")
    table.add_column("Depth m")
    table.add_column("Lat")
    table.add_column("Lon")
    for r in results:
        depth = ""
        if r.depth_min_m is not None or r.depth_max_m is not None:
            depth = f"{r.depth_min_m or '?'}–{r.depth_max_m or '?'}"
        table.add_row(
            r.name,
            ", ".join(r.site_types),
            r.country_code or "",
            r.locality or "",
            depth,
            f"{r.lat:.4f}",
            f"{r.lon:.4f}",
        )
    console.print(table)
    console.print(f"{len(results)} result(s)")


@app.command("stats")
def stats_cmd() -> None:
    """Show atlas counts."""
    with session_scope() as session:
        sites = session.scalar(select(func.count()).select_from(DiveSite)) or 0
        regions = session.scalar(select(func.count()).select_from(Region)) or 0
        operators = session.scalar(select(func.count()).select_from(Operator)) or 0
        by_type = session.execute(
            text(
                """
                SELECT unnest(site_types) AS t, COUNT(*) AS n
                FROM dive_sites
                GROUP BY t
                ORDER BY n DESC, t
                """
            )
        ).all()
    console.print(f"Regions:   {regions}")
    console.print(f"Sites:     {sites}")
    console.print(f"Operators: {operators} (enrich later via GIS)")
    if by_type:
        console.print("\nBy type:")
        for t, n in by_type:
            console.print(f"  {t}: {n}")


@app.command("export-geojson")
def export_geojson(
    out: str = typer.Option("dive-sites.geojson", "--out", "-o"),
    country: Optional[str] = typer.Option(None, "--country", "-c"),
) -> None:
    """Export sites as GeoJSON FeatureCollection (for QGIS / debugging)."""
    with session_scope() as session:
        results = search_sites(session, country_code=country, limit=100_000)
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
            "properties": {
                "id": r.id,
                "slug": r.slug,
                "name": r.name,
                "site_types": r.site_types,
                "country_code": r.country_code,
                "locality": r.locality,
                "depth_min_m": r.depth_min_m,
                "depth_max_m": r.depth_max_m,
                "skill_level": r.skill_level,
                "confidence": r.confidence,
                "tags": r.tags,
            },
        }
        for r in results
    ]
    payload = {"type": "FeatureCollection", "features": features}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    console.print(f"[green]Wrote[/green] {len(features)} features → {out}")


if __name__ == "__main__":
    app()
