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
from dive_atlas.models import (
    Base,
    DiveSite,
    Magazine,
    MagazineArticle,
    MagazineIssue,
    Operator,
    Region,
)
from dive_atlas.services.ingest import ingest_batch
from dive_atlas.services.magazines import ingest_magazine_crawl, sync_registry
from dive_atlas.services.search import search_sites
from dive_atlas.ingest.magazines import MagazineWebCrawler, load_magazine_registry

app = typer.Typer(
    name="dive-atlas",
    help="Global dive site atlas — PostGIS knowledge graph (no website required).",
    no_args_is_help=True,
)
mag_app = typer.Typer(help="Dive magazine registry + issue/article harvest")
app.add_typer(mag_app, name="magazines")
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
    adapter: str = typer.Argument(..., help="Adapter slug, e.g. seed-famous | padi-travel | all"),
) -> None:
    """Run a crawler adapter and upsert into PostGIS."""
    load_all_adapters()
    slugs = list_adapters() if adapter == "all" else [adapter]
    # Prefer high-coverage sources last so higher-confidence seed/PADI can win on coords
    priority = {
        "open-data-stub": 0,
        "wikidata": 1,
        "osm-overpass": 2,
        "padi-travel": 3,
        "seed-famous": 4,
    }
    slugs = sorted(slugs, key=lambda s: priority.get(s, 10))
    total_sites = 0
    for slug in slugs:
        if slug == "open-data-stub":
            continue
        console.print(f"[cyan]Fetching[/cyan] {slug}…")
        batch = get_adapter(slug).fetch()
        with session_scope() as session:
            stats = ingest_batch(session, batch)
        total_sites += stats["sites"]
        console.print(
            f"[green]Ingested[/green] {stats['regions']} regions, {stats['sites']} sites "
            f"from [bold]{slug}[/bold]  meta={batch.meta}"
        )
    console.print(f"[bold]Done.[/bold] Site upserts this run: {total_sites}")


@app.command("harvest")
def harvest_cmd() -> None:
    """Pull everything from all live adapters (PADI + OSM + Wikidata + seed)."""
    ingest_cmd("all")


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
        magazines = session.scalar(select(func.count()).select_from(Magazine)) or 0
        issues = session.scalar(select(func.count()).select_from(MagazineIssue)) or 0
        articles = session.scalar(select(func.count()).select_from(MagazineArticle)) or 0
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
    console.print(f"Regions:    {regions}")
    console.print(f"Sites:      {sites}")
    console.print(f"Operators:  {operators} (enrich later via GIS)")
    console.print(f"Magazines:  {magazines}")
    console.print(f"Issues:     {issues}")
    console.print(f"Articles:   {articles}")
    if by_type:
        console.print("\nBy type:")
        for t, n in by_type:
            console.print(f"  {t}: {n}")


@mag_app.command("sync")
def magazines_sync() -> None:
    """Load dive_magazines.json registry into PostGIS."""
    mags = load_magazine_registry()
    with session_scope() as session:
        n = sync_registry(session, mags)
    console.print(f"[green]Synced[/green] {n} magazines from registry.")


@mag_app.command("list")
def magazines_list(
    language: Optional[str] = typer.Option(None, "--lang", "-l"),
    limit: int = typer.Option(100, "--limit", "-n"),
) -> None:
    """List registered magazines."""
    mags = load_magazine_registry()
    if language:
        mags = [m for m in mags if language in (m.languages or [m.language])]
    table = Table(title="Dive magazines")
    table.add_column("Prio")
    table.add_column("Slug")
    table.add_column("Name")
    table.add_column("Lang")
    table.add_column("Countries")
    table.add_column("Focus")
    for m in mags[:limit]:
        table.add_row(
            str(m.priority),
            m.slug,
            m.name_local or m.name,
            m.language,
            ",".join(m.countries),
            ",".join(m.focus[:4]),
        )
    console.print(table)
    console.print(f"{len(mags)} magazine(s)")


@mag_app.command("harvest")
def magazines_harvest(
    years: int = typer.Option(15, "--years", "-y", help="Lookback years for dated content"),
    max_articles: int = typer.Option(80, "--max-articles", help="Max articles per magazine"),
    priority_max: int = typer.Option(2, "--priority-max", help="Only magazines with priority <= N"),
    slug: Optional[str] = typer.Option(None, "--slug", help="Harvest a single magazine slug"),
    limit_magazines: Optional[int] = typer.Option(
        None, "--limit-magazines", help="Cap number of magazines this run"
    ),
) -> None:
    """Crawl magazine web archives and ingest issues/articles (multi-language).

    Designed to scale to full issue archives: start with HTML web content,
    then add per-publisher PDF/OCR adapters without changing the schema.
    """
    mags = load_magazine_registry()
    if slug:
        mags = [m for m in mags if m.slug == slug]
    else:
        mags = [m for m in mags if m.priority <= priority_max and m.base_url]
    if limit_magazines is not None:
        mags = mags[:limit_magazines]

    with session_scope() as session:
        sync_registry(session, load_magazine_registry())

    total_articles = 0
    total_issues = 0
    for mag in mags:
        console.print(
            f"[cyan]Crawling[/cyan] {mag.slug} ({mag.language}) {mag.archive_url or mag.base_url}"
        )
        crawler = MagazineWebCrawler(
            mag, max_articles=max_articles, lookback_years=years
        )
        try:
            issues, articles = crawler.crawl()
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Failed[/red] {mag.slug}: {exc}")
            continue
        with session_scope() as session:
            stats = ingest_magazine_crawl(session, mag, issues, articles)
        total_issues += stats["issues"]
        total_articles += stats["articles"]
        places = sum(1 for a in articles if a.place_mentions)
        console.print(
            f"  → {stats['issues']} issues, {stats['articles']} articles "
            f"({places} with place mentions)"
        )
    console.print(
        f"[bold]Magazine harvest done.[/bold] issues={total_issues} articles={total_articles}"
    )


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
