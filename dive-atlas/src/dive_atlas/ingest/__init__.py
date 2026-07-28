"""Ingest package — import adapters for registry side effects."""

from dive_atlas.ingest import open_data_stub as open_data_stub  # noqa: F401
from dive_atlas.ingest import seed as seed  # noqa: F401
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
]
