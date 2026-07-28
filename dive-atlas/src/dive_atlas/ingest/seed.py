from __future__ import annotations

import json
from pathlib import Path

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.schemas import DiveSiteIn, RegionIn, SeasonalityIn
from dive_atlas.taxonomy import SourceKind

SEED_PATH = Path(__file__).resolve().parents[3] / "data" / "seeds" / "famous_sites.json"


@register_adapter
class SeedAtlasAdapter(CrawlerAdapter):
    """Curated seed corpus: famous sites across caves, cenotes, reefs, wrecks, atolls."""

    slug = "seed-famous"
    name = "Famous dive sites seed corpus"
    kind = SourceKind.SEED

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or SEED_PATH

    def fetch(self) -> IngestBatch:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        regions = [RegionIn.model_validate(r) for r in data.get("regions", [])]
        sites: list[DiveSiteIn] = []
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
            regions=regions,
            sites=sites,
            meta={"path": str(self.path)},
        )
