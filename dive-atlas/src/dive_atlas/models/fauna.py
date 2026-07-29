"""Marine fauna atlas — taxa + site occurrence links for ID cards and area guides."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dive_atlas.models.base import UUID_PK, Base, TimestampMixin, new_uuid


class Taxon(Base, TimestampMixin):
    """Canonical dive animal / plant / coral entry (encyclopedia + ID card feedstock)."""

    __tablename__ = "taxa"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_taxa_slug"),
        Index("ix_taxa_group", "taxon_group"),
        Index("ix_taxa_common_name", "common_name"),
        Index("ix_taxa_aliases", "aliases", postgresql_using="gin"),
        Index("ix_taxa_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    common_name: Mapped[str] = mapped_column(String(200), nullable=False)
    scientific_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    taxon_group: Mapped[str] = mapped_column(String(40), nullable=False, default="fish")
    # fish | shark | ray | mammal | reptile | invert | coral | plant | other
    rank: Mapped[str] = mapped_column(String(40), nullable=False, default="species_group")
    # species | genus | family | species_group | morphotype
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    id_tips: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    size_cm_typical: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    habitat: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    danger_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    card_worthy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    # macro | pelagic | charismatic | invasive | venomous | cleaning_station | ...
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # worms_id, gbif_id, iucn, image_url hints, etc.


class SiteTaxon(Base, TimestampMixin):
    """Observed / reported occurrence of a taxon at a dive site."""

    __tablename__ = "site_taxa"
    __table_args__ = (
        UniqueConstraint("site_id", "taxon_id", "source", name="uq_site_taxa_site_taxon_source"),
        Index("ix_site_taxa_site_id", "site_id"),
        Index("ix_site_taxa_taxon_id", "taxon_id"),
        Index("ix_site_taxa_source", "source"),
        Index("ix_site_taxa_likelihood", "likelihood"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    site_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("dive_sites.id", ondelete="CASCADE"), nullable=False
    )
    taxon_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("taxa.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="padi")
    # padi | seasonality | phenomenon | magazine | sighting | seed | manual
    likelihood: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    # 0–1 chance / relative frequency for trip planning + cards
    seasonality_hint: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    raw_label: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
