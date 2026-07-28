from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dive_atlas.models.base import UUID_PK, Base, TimestampMixin, new_uuid


class Magazine(Base, TimestampMixin):
    """A dive periodical / web magazine (any language, any region)."""

    __tablename__ = "magazines"
    __table_args__ = (UniqueConstraint("slug", name="uq_magazines_slug"),)

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    name_local: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    languages: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    countries: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    regions: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    archive_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    focus: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    issues: Mapped[list[MagazineIssue]] = relationship(
        back_populates="magazine", cascade="all, delete-orphan"
    )
    articles: Mapped[list[MagazineArticle]] = relationship(
        back_populates="magazine", cascade="all, delete-orphan"
    )


class MagazineIssue(Base, TimestampMixin):
    """One issue / edition (print or digital) of a magazine."""

    __tablename__ = "magazine_issues"
    __table_args__ = (
        UniqueConstraint("magazine_id", "external_id", name="uq_magazine_issues_external"),
        Index("ix_magazine_issues_magazine_id", "magazine_id"),
        Index("ix_magazine_issues_published_on", "published_on"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    magazine_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("magazines.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(240), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    issue_number: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    published_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    pdf_url: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    magazine: Mapped[Magazine] = relationship(back_populates="issues")
    articles: Mapped[list[MagazineArticle]] = relationship(back_populates="issue")


class MagazineArticle(Base, TimestampMixin):
    """Article / feature extracted from a magazine issue or web archive."""

    __tablename__ = "magazine_articles"
    __table_args__ = (
        UniqueConstraint("magazine_id", "external_id", name="uq_magazine_articles_external"),
        Index("ix_magazine_articles_magazine_id", "magazine_id"),
        Index("ix_magazine_articles_issue_id", "issue_id"),
        Index("ix_magazine_articles_published_on", "published_on"),
        Index("ix_magazine_articles_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(UUID_PK, primary_key=True, default=new_uuid)
    magazine_id: Mapped[str] = mapped_column(
        UUID_PK, ForeignKey("magazines.id", ondelete="CASCADE"), nullable=False
    )
    issue_id: Mapped[Optional[str]] = mapped_column(
        UUID_PK, ForeignKey("magazine_issues.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str] = mapped_column(String(240), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    authors: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    published_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Place / site strings mined from the article for later GIS linking
    place_mentions: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    site_slugs: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    magazine: Mapped[Magazine] = relationship(back_populates="articles")
    issue: Mapped[Optional[MagazineIssue]] = relationship(back_populates="articles")
