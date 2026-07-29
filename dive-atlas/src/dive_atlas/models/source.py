from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dive_atlas.models.base import UUID_PK, Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from dive_atlas.models.site import DiveSite


class DataSource(Base, TimestampMixin):
    """A named ingest pipeline or dataset (seed, open data, magazine, PADI…)."""

    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("slug", name="uq_data_sources_slug"),)

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    records: Mapped[list[SourceRecord]] = relationship(back_populates="source")


class SourceRecord(Base, TimestampMixin):
    """Provenance: one external observation linked to a dive site (or pending match)."""

    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_source_records_external"),
        Index("ix_source_records_site_id", "site_id"),
        Index("ix_source_records_source_id", "source_id"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    source_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[Optional[str]] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str] = mapped_column(String(240), nullable=False)
    external_url: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source: Mapped[DataSource] = relationship(back_populates="records")
    site: Mapped[Optional[DiveSite]] = relationship(back_populates="source_records")
