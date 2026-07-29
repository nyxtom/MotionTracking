from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field


class MagazineIn(BaseModel):
    slug: str
    name: str
    name_local: Optional[str] = None
    language: str = "en"
    languages: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    base_url: Optional[str] = None
    archive_url: Optional[str] = None
    focus: list[str] = Field(default_factory=list)
    status: str = "unknown"
    priority: int = 5
    notes: Optional[str] = None
    properties: dict[str, Any] = Field(default_factory=dict)


class MagazineIssueIn(BaseModel):
    magazine_slug: str
    external_id: str
    title: Optional[str] = None
    issue_number: Optional[str] = None
    published_on: Optional[date] = None
    year: Optional[int] = None
    month: Optional[int] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    language: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class MagazineArticleIn(BaseModel):
    magazine_slug: str
    issue_external_id: Optional[str] = None
    external_id: str
    title: str
    url: Optional[str] = None
    authors: list[str] = Field(default_factory=list)
    published_on: Optional[date] = None
    language: Optional[str] = None
    summary: Optional[str] = None
    body_text: Optional[str] = None
    place_mentions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    raw: dict[str, Any] = Field(default_factory=dict)
