# Dive Atlas

Global dive site atlas: a PostGIS knowledge graph of **underwater places** —
reefs, walls, wrecks, flooded caves, caverns, cenotes, atolls, blue holes, springs,
muck, quarries, ice, research habitats / undersea labs, coral occurrence points.

**In:** anything under (or flooded by) water. Flag `diveable` + `access`
(`recreational` | `restricted` | `research_only` | `private` | `closed` | `unknown`)
so Aquarius-class labs sit next to charter reefs without confusion.

**Out:** dry terrestrial caves, archaeology sites, show caves, dive shops-as-sites,
indoor pools — e.g. Amud / Tabun in Israel never belong here.

PADI-style catalogs that only expose ~bookable inventory are intentionally *not*
the source of truth. This atlas aims for complete geographic coverage first;
shops and operators are enriched later with GIS proximity (Places / OSM / etc.).

## What this is

| Layer | Role |
|-------|------|
| **Regions** | Hierarchical containers (ocean → country → coast → park) |
| **Dive sites** | Point (+ optional footprint) with types, depths, skill, **diveable/access**, tags |
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
dive-atlas ingest seed-habitats   # Aquarius Reef Base (research_only), Jules' Lodge, …
dive-atlas stats
dive-atlas search --type cenote
dive-atlas search -q Okinawa
dive-atlas search --access research_only
dive-atlas search --not-diveable -n 20
dive-atlas search --near 126.56,33.24 --radius-km 200
dive-atlas export-geojson -o sites.geojson
```

## Crawler adapters

Adapters normalize heterogeneous inputs into `DiveSiteIn` / `RegionIn`.
They never write SQL directly — `services.ingest` upserts with provenance.

| Slug | Status |
|------|--------|
| `seed-famous` | Curated world seed (Florida caves, Yucatán cenotes, wrecks, atolls…) |
| `seed-habitats` | Undersea labs / habitats with `diveable` + `access` flags (Aquarius, Jules’) |
| `padi-travel` | Full PADI Travel catalog (~4.8k) via public travel API + adaptive map tiles |
| `osm-overpass` | OSM scuba / wreck / dive nodes by region (Overpass) |
| `wikidata` | Wikidata wrecks, cenotes, reefs, **sea / flooded caves** (not terrestrial caves), blue holes |
| `opendivemap` | OpenDiveMap open GeoJSON API (community sites, no auth) |
| `operator-maps` | Curated marine-park / shop maps (`data/sources/operator_maps.json` — KML/GPX/My Maps) |
| `openseamap` | OpenSeaMap seamarks: mooring / wreck / rock / reef (boat-chart points) |
| `osm-mpa` | OSM protected areas / national parks → atlas regions |
| `coral-reefs` | WRI/UNEP global coral reef centroids + cold-water coral points |
| `open-data-stub` | Placeholder |

```bash
dive-atlas harvest          # all live adapters
dive-atlas ingest padi-travel
dive-atlas ingest osm-overpass
dive-atlas ingest wikidata
dive-atlas analyze-quality          # corpus diveability audit
dive-atlas purge-junk               # caves / Canmore wrecks / OSM shops / pools
dive-atlas map --region roatan      # OSM basemap + dive flags → PNG
dive-atlas map --region japan --no-labels
dive-atlas map --all
dive-atlas ingest opendivemap       # OpenDiveMap community GeoJSON (~3k+)
dive-atlas ingest operator-maps     # marine-park / shop Google My Maps (registry)
dive-atlas ingest openseamap        # boat-chart seamarks (mooring/wreck/rock/reef)
dive-atlas ingest osm-mpa           # protected areas → regions
dive-atlas ingest coral-reefs       # global coral habitat points
dive-atlas enrich-gebco             # GEBCO depth sample at every site
dive-atlas stats
```

### Operator maps (worldwide)

There is no single “all shop maps” API. The atlas grows coverage in layers:

1. **Bulk baselines** — `opendivemap`, `padi-travel`, `osm-overpass`
2. **Official park GPS** — add KML/GPX/`google_my_maps` entries to `data/sources/operator_maps.json`
3. **Public shop My Maps** — same registry (`mid` + `forcekml=1`)
4. **Later** — crawl known `operators.website` for embedded map IDs

Example (Roatán Marine Park, ~400 sites): already in the registry as `roatan-marine-park`.

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

## Magazines (every region / language)

Registry: `data/sources/dive_magazines.json` — JA/KO/ZH/ES/PT/DE/FR/IT/NL/SV/NO/PL/RU/TR/EN titles.

Schema stores **magazines → issues → articles** with `place_mentions` mined for later site linking.
The web crawler pulls HTML archives now; per-publisher PDF/OCR issue scrapers plug into the same tables.

```bash
dive-atlas init-db
dive-atlas magazines sync
dive-atlas magazines list --lang ja
dive-atlas magazines harvest --years 15 --priority-max 2 --max-articles 100
dive-atlas magazines harvest --slug x-ray-mag --years 20 --max-articles 500
dive-atlas stats
```

Plan for “every issue for last X years”: registry sync → HTML archive harvest → publisher-specific PDF/Issuu/OCR adapters → NLP link `place_mentions` → `dive_sites`.

## Product ontology (what the atlas powers)

| Product surface | Atlas tables |
|-----------------|--------------|
| Trip composer | `site_profiles` + seasonality + `phenomenon_occurrences` → `trip-compose` |
| Phenomena calendar | `phenomena`, `phenomenon_occurrences` |
| Skill-gated exploration | `site_profiles` (certs, overhead, deco, gas, current) |
| Living briefings | `site_briefings` (entry/exit, hazards, chamber, regs) |
| Fleet / conditions | site geom + profiles + (forecast adapters later) |
| Incident intelligence | `incidents` |
| Reef health / MPA | `eco_events` |
| Citizen science | `sightings` (stable `site_id`, not free text) |
| Encyclopedia pages | `site_encyclopedia` |
| Route storytelling | `dive_routes`, `dive_route_stops` |
| AR / VR previews | `survey_assets` (cave surveys, bathymetry, meshes) |

```bash
dive-atlas seed-ontology
dive-atlas trip-compose --days 10 --cert aow --want caves --want pelagics --max-depth 30 --month 2
```

## Layout

```text
dive-atlas/
  data/seeds/famous_sites.json
  data/seeds/product_ontology.json
  data/sources/dive_magazines.json
  docker-compose.yml
  src/dive_atlas/
    taxonomy.py
    ontology.py               # certs, hazards, phenomena, routes, …
    models/                   # sites + capability layers
    ingest/                   # crawlers
    services/                 # ingest, search, trip composer, magazines
    cli.py
```

## License

MIT (same spirit as the rest of the scuba tooling ecosystem).
