from __future__ import annotations

import json
from pathlib import Path

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.schemas import DiveSiteIn, RegionIn, SeasonalityIn
from dive_atlas.taxonomy import SourceKind

SEED_PATH = Path(__file__).resolve().parents[3] / "data" / "seeds" / "famous_sites.json"
SEED_DIR = Path(__file__).resolve().parents[3] / "data" / "seeds"


@register_adapter
class SeedAtlasAdapter(CrawlerAdapter):
    """Curated seed corpus: famous sites across caves, cenotes, reefs, wrecks, atolls."""

    slug = "seed-famous"
    name = "Famous dive sites seed corpus"
    kind = SourceKind.SEED

    def __init__(self, path: Path | None = None, glob: str = "famous_sites.json") -> None:
        self.path = path
        self.glob = glob

    def fetch(self) -> IngestBatch:
        paths = [self.path] if self.path else sorted(SEED_DIR.glob(self.glob))
        if not paths:
            paths = [SEED_PATH]
        regions: dict[str, RegionIn] = {}
        sites: list[DiveSiteIn] = []
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            for r in data.get("regions", []):
                region = RegionIn.model_validate(r)
                regions[region.slug] = region
            for raw in data.get("sites", []):
                item = dict(raw)
                seasons = [SeasonalityIn.model_validate(s) for s in item.pop("seasonality", [])]
                site = DiveSiteIn.model_validate({**item, "seasonality": seasons})
                site.raw = raw
                sites.append(site)
        return IngestBatch(
            source_slug=self.slug,
            source_name=self.name,
            source_kind=self.kind,
            regions=list(regions.values()),
            sites=sites,
            meta={"paths": [str(p) for p in paths], "sites": len(sites)},
        )


@register_adapter
class SeedRajaAmpatAdapter(SeedAtlasAdapter):
    """Raja Ampat curated boat-drop / liveaboard site seed."""

    slug = "seed-raja-ampat"
    name = "Raja Ampat dive sites seed"
    kind = SourceKind.SEED

    def __init__(self, path: Path | None = None) -> None:
        super().__init__(path=path or (SEED_DIR / "raja_ampat_sites.json"))


@register_adapter
class SeedKomodoAdapter(SeedAtlasAdapter):
    slug = "seed-komodo"
    name = "Komodo dive sites seed"
    kind = SourceKind.SEED

    def __init__(self, path: Path | None = None) -> None:
        super().__init__(path=path or (SEED_DIR / "komodo_sites.json"))


@register_adapter
class SeedPalauTrukAdapter(SeedAtlasAdapter):
    slug = "seed-palau-truk"
    name = "Palau + Truk Lagoon dive sites seed"
    kind = SourceKind.SEED

    def __init__(self, path: Path | None = None) -> None:
        super().__init__(path=path or (SEED_DIR / "palau_truk_sites.json"))


@register_adapter
class SeedSipadanAdapter(SeedAtlasAdapter):
    slug = "seed-sipadan"
    name = "Sipadan / Mabul dive sites seed"
    kind = SourceKind.SEED

    def __init__(self, path: Path | None = None) -> None:
        super().__init__(path=path or (SEED_DIR / "sipadan_sites.json"))


@register_adapter
class SeedGalapagosCenotesAdapter(SeedAtlasAdapter):
    slug = "seed-galapagos-cenotes"
    name = "Galápagos + Tulum cenotes seed"
    kind = SourceKind.SEED

    def __init__(self, path: Path | None = None) -> None:
        super().__init__(path=path or (SEED_DIR / "galapagos_cenotes_sites.json"))
