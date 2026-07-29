from dive_atlas.ingest import coral_reefs as coral_reefs  # noqa: F401
from dive_atlas.ingest import dense as dense  # noqa: F401
from dive_atlas.ingest import opendivemap as opendivemap  # noqa: F401
from dive_atlas.ingest import openseamap as openseamap  # noqa: F401
from dive_atlas.ingest import operator_maps as operator_maps  # noqa: F401
from dive_atlas.ingest import osm as osm  # noqa: F401
from dive_atlas.ingest import osm_mpa as osm_mpa  # noqa: F401
from dive_atlas.ingest import open_data_stub as open_data_stub  # noqa: F401
from dive_atlas.ingest import padi as padi  # noqa: F401
from dive_atlas.ingest import seed as seed  # noqa: F401
from dive_atlas.ingest import wikidata as wikidata  # noqa: F401
from dive_atlas.ingest.base import (
    ADAPTER_REGISTRY,
    CrawlerAdapter,
    IngestBatch,
    get_adapter,
    list_adapters,
    load_all_adapters,
    register_adapter,
)

__all__ = [
    "ADAPTER_REGISTRY",
    "CrawlerAdapter",
    "IngestBatch",
    "get_adapter",
    "list_adapters",
    "load_all_adapters",
    "register_adapter",
    "seed",
    "open_data_stub",
    "padi",
    "osm",
    "wikidata",
    "dense",
    "opendivemap",
    "operator_maps",
    "openseamap",
    "osm_mpa",
    "coral_reefs",
]
