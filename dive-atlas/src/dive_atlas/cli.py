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
    DiveRoute,
    DiveSite,
    Magazine,
    MagazineArticle,
    MagazineIssue,
    Operator,
    Phenomenon,
    Region,
    SiteBriefing,
    SiteProfile,
    SiteTaxon,
    Taxon,
)
from dive_atlas.services.dedupe import dedupe_sites
from dive_atlas.services.quality import (
    analyze_corpus,
    demote_wikidata_reef_confidence,
    purge_all_junk,
    purge_junk_wikidata_wrecks,
    purge_non_diveable_wikidata_caves,
)
from dive_atlas.services.fauna import (
    export_id_cards,
    fauna_for_area,
    fauna_for_site,
    fauna_stats,
    infer_region_fauna,
    mine_padi_marine_life,
    mine_seasonality_highlights,
    sync_fauna_seed,
)
from dive_atlas.services.geo_enrich import enrich_sites_geo
from dive_atlas.services.gebco import enrich_sites_gebco
from dive_atlas.services.ingest import ingest_batch
from dive_atlas.services.magazines import ingest_magazine_crawl, sync_registry
from dive_atlas.services.ontology_seed import seed_product_ontology
from dive_atlas.services.search import search_sites
from dive_atlas.services.trip import TripRequest, compose_trip
from dive_atlas.ingest.magazines import MagazineWebCrawler, load_magazine_registry

app = typer.Typer(
    name="dive-atlas",
    help="Global dive site atlas — PostGIS knowledge graph (no website required).",
    no_args_is_help=True,
)
mag_app = typer.Typer(help="Dive magazine registry + issue/article harvest")
fauna_app = typer.Typer(help="Fish / animal atlas — taxa, site occurrences, ID cards")
app.add_typer(mag_app, name="magazines")
app.add_typer(fauna_app, name="fauna")
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
        "coral-reefs": 2,
        "openseamap": 3,
        "opendivemap": 4,
        "osm-overpass": 5,
        "osm-mpa": 5,
        "dense-hotspots": 6,
        "operator-maps": 7,
        "padi-travel": 8,
        "seed-raja-ampat": 9,
        "seed-komodo": 9,
        "seed-palau-truk": 9,
        "seed-sipadan": 9,
        "seed-galapagos-cenotes": 9,
        "seed-habitats": 9,
        "seed-famous": 10,
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
    diveable: Optional[bool] = typer.Option(
        None, "--diveable/--not-diveable", help="Filter recreational/authorized diveability"
    ),
    access: Optional[str] = typer.Option(
        None,
        "--access",
        help="recreational|restricted|research_only|private|closed|unknown",
    ),
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
            diveable=diveable,
            access=access,
            limit=limit,
        )

    table = Table(title="Dive sites")
    table.add_column("Name")
    table.add_column("Types")
    table.add_column("Diveable")
    table.add_column("Access")
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
            "yes" if r.diveable else "no",
            r.access or "",
            r.country_code or "",
            r.locality or "",
            depth,
            f"{r.lat:.4f}",
            f"{r.lon:.4f}",
        )
    console.print(table)
    console.print(f"{len(results)} result(s)")


@app.command("dense")
def dense_cmd(
    hotspot: Optional[str] = typer.Option(
        None, "--hotspot", help="Comma-separated hotspot slugs (default: all)"
    ),
    skip: Optional[str] = typer.Option(
        None, "--skip", help="Comma-separated hotspot slugs to skip"
    ),
    include_padi: bool = typer.Option(True, "--padi/--no-padi"),
) -> None:
    """Fine-tile crawl of dive hotspots (OSM + optional PADI map pins)."""
    load_all_adapters()
    kwargs: dict = {"include_padi": include_padi}
    if hotspot:
        kwargs["hotspot"] = hotspot
    if skip:
        kwargs["skip"] = [s.strip() for s in skip.split(",") if s.strip()]
    console.print(f"[cyan]Dense crawl[/cyan] {kwargs or 'all hotspots'}…")
    batch = get_adapter("dense-hotspots", **kwargs).fetch()
    with session_scope() as session:
        stats = ingest_batch(session, batch)
    console.print(
        f"[green]Ingested[/green] {stats['regions']} regions, {stats['sites']} sites "
        f"meta={batch.meta}"
    )


@app.command("map")
def map_cmd(
    region: Optional[str] = typer.Option(
        None,
        "--region",
        "-r",
        help="Preset: roatan, bay-islands, okinawa, yaeyama, japan, izu",
    ),
    bbox: Optional[str] = typer.Option(
        None, "--bbox", help="south,west,north,east (decimal degrees)"
    ),
    title: Optional[str] = typer.Option(None, "--title", help="Map title"),
    out: Optional[str] = typer.Option(
        None, "--out", "-o", help="Output PNG path"
    ),
    labels: bool = typer.Option(True, "--labels/--no-labels"),
    heatmap: bool = typer.Option(True, "--heatmap/--no-heatmap"),
    all_presets: bool = typer.Option(False, "--all", help="Render every preset region"),
) -> None:
    """Render a static OSM map with dive-flag markers for a region."""
    from pathlib import Path

    from dive_atlas.viz.maps import PRESET_REGIONS, render_dive_map, render_preset, sites_in_bbox

    out_dir = Path("/opt/cursor/artifacts/maps")
    out_dir.mkdir(parents=True, exist_ok=True)

    with session_scope() as session:
        if all_presets:
            for slug in PRESET_REGIONS:
                info = render_preset(
                    session, slug, out_dir=out_dir, show_labels=labels, heatmap=heatmap
                )
                console.print(
                    f"[green]Map[/green] {slug}: {info['sites']} sites → {info['path']}"
                )
            return
        if region:
            reg = PRESET_REGIONS.get(region)
            if reg is None:
                console.print("Presets: " + ", ".join(sorted(PRESET_REGIONS)))
                raise typer.BadParameter(f"Unknown region {region!r}")
            pins = sites_in_bbox(
                session,
                south=reg.south,
                west=reg.west,
                north=reg.north,
                east=reg.east,
            )
            path = Path(out) if out else out_dir / f"dive-map-{reg.slug}.png"
            info = render_dive_map(
                pins,
                south=reg.south,
                west=reg.west,
                north=reg.north,
                east=reg.east,
                title=title or reg.title,
                out_path=path,
                zoom=reg.zoom,
                show_labels=labels and len(pins) <= 80,
                heatmap=heatmap,
            )
            console.print(f"[green]Map[/green] {info['sites']} sites → {info['path']}")
            return
        if bbox:
            parts = [float(x.strip()) for x in bbox.split(",")]
            if len(parts) != 4:
                raise typer.BadParameter("bbox must be south,west,north,east")
            south, west, north, east = parts
            pins = sites_in_bbox(
                session, south=south, west=west, north=north, east=east
            )
            path = Path(out) if out else out_dir / "dive-map-custom.png"
            info = render_dive_map(
                pins,
                south=south,
                west=west,
                north=north,
                east=east,
                title=title or "Dive sites",
                out_path=path,
                show_labels=labels and len(pins) <= 80,
                heatmap=heatmap,
            )
            console.print(f"[green]Map[/green] {info['sites']} sites → {info['path']}")
            return
        console.print("Presets: " + ", ".join(sorted(PRESET_REGIONS)))
        raise typer.BadParameter("Pass --region, --bbox, or --all")


@app.command("enrich-geo")
def enrich_geo_cmd(
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Cap sites scanned"),
) -> None:
    """Backfill country_code + locality from coords, PADI URLs, and dive-area bboxes."""
    with session_scope() as session:
        stats = enrich_sites_geo(session, limit=limit)
    console.print(f"[green]Geo enrich[/green] {stats}")


@app.command("enrich-gebco")
def enrich_gebco_cmd(
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Cap sites (testing)"),
    all_sites: bool = typer.Option(
        False, "--all", help="Re-sample even if gebco_* already present"
    ),
) -> None:
    """Sample GEBCO bathymetry at each site (OpenTopoData gebco2020)."""
    with session_scope() as session:
        stats = enrich_sites_gebco(
            session, limit=limit, only_missing=not all_sites
        )
    console.print(
        f"[green]GEBCO enrich[/green] scanned={stats.scanned} updated={stats.updated} "
        f"underwater={stats.underwater} land={stats.land} errors={len(stats.errors)}"
    )
    for err in stats.errors[:5]:
        console.print(f"  [red]{err}[/red]")


@app.command("seed-ontology")
def seed_ontology_cmd() -> None:
    """Load phenomena, routes, skill profiles, and briefings seed data."""
    with session_scope() as session:
        stats = seed_product_ontology(session)
    console.print(f"[green]Ontology seed[/green] {stats}")


@app.command("trip-compose")
def trip_compose_cmd(
    days: int = typer.Option(10, "--days"),
    cert: list[str] = typer.Option(["aow"], "--cert", help="Repeatable cert flags"),
    want: list[str] = typer.Option([], "--want", "-w", help="caves, pelagics, wreck, ..."),
    max_depth: float = typer.Option(30.0, "--max-depth"),
    month: Optional[int] = typer.Option(None, "--month", "-m"),
    avoid_monsoon: bool = typer.Option(True, "--avoid-monsoon/--allow-monsoon"),
    allow_overhead: bool = typer.Option(False, "--allow-overhead"),
    allow_deco: bool = typer.Option(False, "--allow-deco"),
    country: Optional[str] = typer.Option(None, "--country", "-c"),
    limit: int = typer.Option(15, "--limit", "-n"),
) -> None:
    """Rank itinerary candidates from trip intent (skill-gated)."""
    req = TripRequest(
        days=days,
        certs=cert,
        want=want,
        max_depth_m=max_depth,
        travel_month=month,
        avoid_monsoon=avoid_monsoon,
        allow_overhead=allow_overhead,
        allow_deco=allow_deco,
        country_codes=[country] if country else [],
        limit=limit,
    )
    with session_scope() as session:
        results = compose_trip(session, req)
    table = Table(title=f"Trip candidates ({days}d, cert={','.join(cert)})")
    table.add_column("Score")
    table.add_column("Name")
    table.add_column("Types")
    table.add_column("Depth")
    table.add_column("Where")
    table.add_column("Why")
    table.add_column("Backup")
    for r in results:
        table.add_row(
            f"{r.score:.2f}",
            r.name,
            ",".join(r.site_types),
            "" if r.depth_max_m is None else str(r.depth_max_m),
            f"{r.country_code or ''} {r.locality or ''}".strip(),
            "; ".join(r.reasons),
            "yes" if r.backup else "",
        )
    console.print(table)


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
        profiles = session.scalar(select(func.count()).select_from(SiteProfile)) or 0
        briefings = session.scalar(select(func.count()).select_from(SiteBriefing)) or 0
        phenomena = session.scalar(select(func.count()).select_from(Phenomenon)) or 0
        routes = session.scalar(select(func.count()).select_from(DiveRoute)) or 0
        fauna = fauna_stats(session)
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
    console.print(f"Profiles:   {profiles}")
    console.print(f"Briefings:  {briefings}")
    console.print(f"Phenomena:  {phenomena}")
    console.print(f"Routes:     {routes}")
    console.print(
        f"Fauna:      {fauna['taxa']} taxa · {fauna['site_taxon_links']} site links · "
        f"{fauna['sites_with_fauna']} sites"
    )
    if by_type:
        console.print("\nBy type:")
        for t, n in by_type:
            console.print(f"  {t}: {n}")


@fauna_app.command("sync")
def fauna_sync_cmd() -> None:
    """Load data/seeds/fauna_taxa.json into the taxa catalog."""
    with session_scope() as session:
        # Ensure tables exist when fauna is added mid-flight
        Base.metadata.create_all(session.get_bind())
        stats = sync_fauna_seed(session)
    console.print(f"[green]Fauna sync[/green] {stats}")


@app.command("dedupe")
def dedupe_cmd(
    distance_m: float = typer.Option(150.0, "--distance-m", help="Max distance for same-name merge"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report clusters without merging"),
) -> None:
    """Merge near-duplicate sites (same normalized name within distance)."""
    with session_scope() as session:
        stats = dedupe_sites(session, max_distance_m=distance_m, dry_run=dry_run)
    console.print(f"[green]Dedupe[/green] {stats}")


@app.command("analyze-quality")
def analyze_quality_cmd(
    sample: int = typer.Option(6, "--sample", help="Sample names per bucket"),
) -> None:
    """Audit the atlas for non-diveable / misclassified sites."""
    with session_scope() as session:
        report = analyze_corpus(session, sample=sample)
    console.print(f"[bold]Sites[/bold] {report.total_sites:,}")
    console.print(
        f"[bold]Issues[/bold] critical={report.critical_count:,}  warn={report.warn_count:,}"
    )
    table = Table(title="Quality buckets")
    table.add_column("Sev")
    table.add_column("Bucket")
    table.add_column("Count", justify="right")
    table.add_column("Action")
    table.add_column("Samples")
    for b in report.buckets:
        color = {"critical": "red", "warn": "yellow", "info": "cyan"}.get(b.severity, "white")
        table.add_row(
            f"[{color}]{b.severity}[/{color}]",
            b.key,
            f"{b.count:,}",
            b.action,
            "; ".join(b.samples[:3]),
        )
    console.print(table)
    console.print("\nBy source:")
    for slug, n in report.by_source.items():
        console.print(f"  {slug}: {n:,}")


@app.command("purge-junk")
def purge_junk_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Report without deleting"),
    demote_reefs: bool = typer.Option(
        True, "--demote-reefs/--no-demote-reefs", help="Tag Wikidata-only reefs as geo_feature"
    ),
) -> None:
    """Remove critical junk: terrestrial caves, Canmore wrecks, OSM shops, pools, Q-ids."""
    with session_scope() as session:
        results = purge_all_junk(session, dry_run=dry_run)
        demoted = 0
        if demote_reefs and not dry_run:
            demoted = demote_wikidata_reef_confidence(session)
        elif demote_reefs and dry_run:
            demoted = -1  # signal dry
    for key, stats in results.items():
        n = stats.candidates if dry_run else stats.deleted_sites
        extra = ""
        if key == "operators" and stats.migrated_operators:
            extra = f" migrated_ops={stats.migrated_operators}"
        console.print(
            f"[green]{key}[/green] candidates={stats.candidates} "
            f"{'would_delete' if dry_run else 'deleted'}={n}{extra}"
        )
        for name in stats.sample_deleted[:5]:
            console.print(f"    - {name}")
    if demote_reefs:
        console.print(
            f"[green]wikidata reefs[/green] "
            + ("would demote geo_feature" if dry_run else f"demoted={demoted}")
        )


@app.command("purge-junk-caves")
def purge_junk_caves_cmd(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List terrestrial Wikidata caves without deleting"
    ),
) -> None:
    """Remove Wikidata-only terrestrial caves (not diveable)."""
    with session_scope() as session:
        stats = purge_non_diveable_wikidata_caves(session, dry_run=dry_run)
    verb = "Would delete" if dry_run else "Deleted"
    n = stats.candidates if dry_run else stats.deleted_sites
    console.print(
        f"[green]Purge junk caves[/green] candidates={stats.candidates} "
        f"{verb.lower()}={n} "
        f"source_records={stats.deleted_source_records} "
        f"kept_diveable≈{stats.kept_diveable}"
    )
    if stats.sample_deleted:
        console.print("Sample:")
        for name in stats.sample_deleted:
            console.print(f"  - {name}")


@app.command("purge-junk-wrecks")
def purge_junk_wrecks_cmd(
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Remove Wikidata Canmore / Unnamed / Unknown heritage wrecks."""
    with session_scope() as session:
        stats = purge_junk_wikidata_wrecks(session, dry_run=dry_run)
    n = stats.candidates if dry_run else stats.deleted_sites
    console.print(
        f"[green]Purge junk wrecks[/green] candidates={stats.candidates} "
        f"{'would_delete' if dry_run else 'deleted'}={n}"
    )


@fauna_app.command("mine")
def fauna_mine_cmd(
    infer: bool = typer.Option(
        True, "--infer/--no-infer", help="Also infer locality fauna onto unlabeled sites"
    ),
) -> None:
    """Mine PADI marine_life labels + seasonality highlights into site_taxa."""
    with session_scope() as session:
        Base.metadata.create_all(session.get_bind())
        padi = mine_padi_marine_life(session)
        season = mine_seasonality_highlights(session)
        inferred = infer_region_fauna(session) if infer else {"skipped": True}
        totals = fauna_stats(session)
    console.print(f"[green]PADI mine[/green] { {k: v for k, v in padi.items() if k != 'top_unresolved'} }")
    if padi.get("top_unresolved"):
        console.print("Top unresolved labels:")
        for label, n in padi["top_unresolved"][:15]:
            console.print(f"  {n:4d}  {label}")
    console.print(f"[green]Seasonality mine[/green] {season}")
    console.print(f"[green]Region infer[/green] {inferred}")
    console.print(f"[bold]Fauna totals[/bold] {totals}")


@fauna_app.command("infer")
def fauna_infer_cmd(
    min_sites: int = typer.Option(2, "--min-sites", help="Min evidence sites per locality taxon"),
    max_taxa: int = typer.Option(12, "--max-taxa", help="Max inferred taxa per site"),
) -> None:
    """Propagate locality fauna onto sites missing direct labels."""
    with session_scope() as session:
        stats = infer_region_fauna(
            session, min_evidence_sites=min_sites, max_taxa_per_site=max_taxa
        )
        totals = fauna_stats(session)
    console.print(f"[green]Region infer[/green] {stats}")
    console.print(f"[bold]Fauna totals[/bold] {totals}")


@fauna_app.command("at")
def fauna_at_cmd(
    locality: Optional[str] = typer.Option(None, "--locality", "-l", help="e.g. Roatán"),
    country: Optional[str] = typer.Option(None, "--country", "-c"),
    near: Optional[str] = typer.Option(None, "--near", help="lon,lat"),
    radius_km: float = typer.Option(50.0, "--radius-km"),
    site_slug: Optional[str] = typer.Option(None, "--site", help="Exact site slug"),
    limit: int = typer.Option(30, "--limit", "-n"),
) -> None:
    """What you might see at a locality / country / radius / site."""
    near_lon = near_lat = None
    if near:
        parts = near.split(",")
        if len(parts) != 2:
            raise typer.BadParameter("--near must be lon,lat")
        near_lon, near_lat = float(parts[0]), float(parts[1])

    with session_scope() as session:
        if site_slug:
            rows = fauna_for_site(session, site_slug=site_slug)
            table = Table(title=f"Fauna @ {site_slug}")
            table.add_column("Name")
            table.add_column("Group")
            table.add_column("Source")
            table.add_column("Likely")
            table.add_column("Raw")
            for r in rows[:limit]:
                table.add_row(
                    r["common_name"],
                    r["taxon_group"],
                    r["source"],
                    f"{float(r['likelihood']):.2f}",
                    (r.get("raw_label") or "")[:40],
                )
            console.print(table)
            console.print(f"{len(rows)} taxon link(s)")
            return

        hits = fauna_for_area(
            session,
            locality=locality,
            country_code=country,
            near_lon=near_lon,
            near_lat=near_lat,
            radius_m=radius_km * 1000,
            limit=limit,
        )
    title_bits = [b for b in [locality, country, near and f"near {near}"] if b]
    table = Table(title=f"Fauna — {', '.join(title_bits) or 'all'}")
    table.add_column("Name")
    table.add_column("Group")
    table.add_column("Sites")
    table.add_column("Likely")
    table.add_column("Where")
    for h in hits:
        table.add_row(
            h.common_name,
            h.taxon_group,
            str(h.sites),
            f"{h.max_likelihood:.2f}",
            ", ".join(h.sample_localities[:3]),
        )
    console.print(table)
    console.print(f"{len(hits)} taxon(s)")


@fauna_app.command("cards")
def fauna_cards_cmd(
    locality: Optional[str] = typer.Option(None, "--locality", "-l"),
    country: Optional[str] = typer.Option(None, "--country", "-c"),
    near: Optional[str] = typer.Option(None, "--near", help="lon,lat"),
    radius_km: float = typer.Option(80.0, "--radius-km"),
    limit: int = typer.Option(24, "--limit", "-n"),
    out: str = typer.Option("fauna-cards.json", "--out", "-o"),
) -> None:
    """Export an ID-card deck JSON for an area (printout feedstock)."""
    near_lon = near_lat = None
    if near:
        parts = near.split(",")
        if len(parts) != 2:
            raise typer.BadParameter("--near must be lon,lat")
        near_lon, near_lat = float(parts[0]), float(parts[1])
    with session_scope() as session:
        cards = export_id_cards(
            session,
            locality=locality,
            country_code=country,
            near_lon=near_lon,
            near_lat=near_lat,
            radius_m=radius_km * 1000,
            limit=limit,
        )
    payload = {
        "area": {"locality": locality, "country_code": country, "near": near},
        "count": len(cards),
        "cards": cards,
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    console.print(f"[green]Wrote[/green] {len(cards)} ID cards → {out}")


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
