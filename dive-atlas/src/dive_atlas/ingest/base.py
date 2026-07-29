from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from dive_atlas.schemas import DiveSiteIn, RegionIn
from dive_atlas.taxonomy import SourceKind


@dataclass
class IngestBatch:
    source_slug: str
    source_name: str
    source_kind: SourceKind
    regions: list[RegionIn] = field(default_factory=list)
    sites: list[DiveSiteIn] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


class CrawlerAdapter(ABC):
    """Base class for every magazine / open-data / travel-site ingest source.

    Adapters normalize heterogeneous inputs into DiveSiteIn / RegionIn.
    They do not write to the database — the ingest service upserts.
    """

    slug: str
    name: str
    kind: SourceKind = SourceKind.OTHER

    @abstractmethod
    def fetch(self) -> IngestBatch:
        """Pull and normalize records into a batch."""

    def iter_sites(self) -> Iterator[DiveSiteIn]:
        yield from self.fetch().sites


ADAPTER_REGISTRY: dict[str, type[CrawlerAdapter]] = {}


def register_adapter(cls: type[CrawlerAdapter]) -> type[CrawlerAdapter]:
    if not getattr(cls, "slug", None):
        raise ValueError(f"{cls.__name__} missing slug")
    ADAPTER_REGISTRY[cls.slug] = cls
    return cls


def list_adapters() -> list[str]:
    return sorted(ADAPTER_REGISTRY)


def get_adapter(slug: str, **kwargs: Any) -> CrawlerAdapter:
    try:
        return ADAPTER_REGISTRY[slug](**kwargs)
    except KeyError as exc:
        known = ", ".join(list_adapters()) or "(none)"
        raise KeyError(f"Unknown adapter {slug!r}. Known: {known}") from exc


def load_all_adapters() -> Iterable[str]:
    # Import side-effect registration
    from dive_atlas.ingest import dense  # noqa: F401
    from dive_atlas.ingest import opendivemap  # noqa: F401
    from dive_atlas.ingest import operator_maps  # noqa: F401
    from dive_atlas.ingest import osm  # noqa: F401
    from dive_atlas.ingest import open_data_stub  # noqa: F401
    from dive_atlas.ingest import padi  # noqa: F401
    from dive_atlas.ingest import seed  # noqa: F401
    from dive_atlas.ingest import wikidata  # noqa: F401

    return list_adapters()
