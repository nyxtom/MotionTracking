# Dive Atlas

Global dive site atlas: a PostGIS knowledge graph of **everywhere you can dive** —
reefs, walls, wrecks, caves, caverns, cenotes, atolls, blue holes, springs, muck,
quarries, ice — not just the subset a travel desk can book.

PADI-style catalogs that only expose ~bookable inventory are intentionally *not*
the source of truth. This atlas aims for complete geographic coverage first;
shops and operators are enriched later with GIS proximity (Places / OSM / etc.).

## What this is

| Layer | Role |
|-------|------|
| **Regions** | Hierarchical containers (ocean → country → coast → park) |
| **Dive sites** | Point (+ optional footprint) with types, depths, skill, tags |
| **Seasonality** | Per-month scores, temps, wildlife highlights |
| **Sources** | Provenance for every ingest (seed, open data, magazine, API…) |
| **Operators** | Dive shops / liveaboards — linked *after* via `ST_DWithin` |

No website yet. CLI + PostGIS + crawler adapters.

## Quick start

```bash
cd dive-atlas
cp .env.example .env
docker compose up -d
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
dive-atlas init-db
dive-atlas ingest seed-famous
dive-atlas stats
dive-atlas search --type cenote
dive-atlas search -q Okinawa
dive-atlas search --near 126.56,33.24 --radius-km 200
dive-atlas export-geojson -o sites.geojson
```

## Crawler adapters

Adapters normalize heterogeneous inputs into `DiveSiteIn` / `RegionIn`.
They never write SQL directly — `services.ingest` upserts with provenance.

| Slug | Status |
|------|--------|
| `seed-famous` | Curated world seed (Florida caves, Yucatán cenotes, wrecks, atolls…) |
| `padi-travel` | Full PADI Travel catalog (~4.8k) via public travel API + adaptive map tiles |
| `osm-overpass` | OSM scuba / wreck / dive nodes by region (Overpass) |
| `wikidata` | Wikidata wrecks, cenotes, reefs, caves, blue holes with coordinates |
| `open-data-stub` | Placeholder |

```bash
dive-atlas harvest          # all live adapters
dive-atlas ingest padi-travel
dive-atlas ingest osm-overpass
dive-atlas ingest wikidata
dive-atlas stats
```

Add a new source:

```python
from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.taxonomy import SourceKind

@register_adapter
class MyMagazineAdapter(CrawlerAdapter):
    slug = "dive-mag-x"
    name = "Dive Mag X"
    kind = SourceKind.MAGAZINE

    def fetch(self) -> IngestBatch:
        ...
```

## Site taxonomy

`reef`, `wall`, `wreck`, `cave`, `cavern`, `cenote`, `atoll`, `lagoon`,
`blue_hole`, `pinnacle`, `seamount`, `drift`, `muck`, `artificial_reef`,
`quarry`, `lake`, `river`, `spring`, `ice`, `jetty`, `pier`, `canal`,
`pass`, `channel`, `drop_off`, `sand_flat`, `mangrove`, …

Sites can carry **multiple** types (e.g. `cenote` + `cavern`).

## Operator enrichment (later)

```text
dive_sites.geom ──ST_DWithin──▶ operators.geom  →  site_operator_links
```

See `dive_atlas.services.enrich.link_nearby_operators`. Pull shops from Google
Places / OSM *after* the atlas has sites everywhere — don't let booking
inventory define which reefs exist.

## Roadmap (atlas-first)

1. Expand open-data ingest (Wikidata dive sites, OSM `sport=scuba_diving`, marine parks)
2. Dedup / merge by fuzzy name + distance
3. Magazine & travel-site adapters behind the same interface (ToS-aware)
4. Seasonality models per region defaults
5. Flight / fare APIs on top of seasonality + nearest airports

## Layout

```text
dive-atlas/
  data/seeds/famous_sites.json
  docker-compose.yml          # PostGIS 16
  src/dive_atlas/
    taxonomy.py
    models/                   # regions, sites, seasonality, sources, operators
    ingest/                   # crawler adapters
    services/                 # upsert, search, GIS enrich
    cli.py
```

## License

MIT (same spirit as the rest of the scuba tooling ecosystem).
