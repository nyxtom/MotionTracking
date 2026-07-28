"""Placeholder adapter for open geospatial / open-data site imports.

Wire this to Wikidata, OpenStreetMap dive nodes, marine park boundaries, etc.
Prefer structured dumps/APIs over scraping bookable travel catalogs — the atlas
should not be limited to sites you can already book.
"""

from __future__ import annotations

from dive_atlas.ingest.base import CrawlerAdapter, IngestBatch, register_adapter
from dive_atlas.taxonomy import SourceKind


@register_adapter
class OpenDataStubAdapter(CrawlerAdapter):
    slug = "open-data-stub"
    name = "Open data stub (Wikidata / OSM / MPA — not yet wired)"
    kind = SourceKind.OPEN_DATA

    def fetch(self) -> IngestBatch:
        return IngestBatch(
            source_slug=self.slug,
            source_name=self.name,
            source_kind=self.kind,
            regions=[],
            sites=[],
            meta={"status": "stub", "next": ["wikidata", "osm", "protected-planet"]},
        )
