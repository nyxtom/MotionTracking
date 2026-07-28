from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class RegionIn(BaseModel):
    slug: str
    name: str
    kind: str = "custom"
    parent_slug: Optional[str] = None
    country_code: Optional[str] = None
    description: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


class SeasonalityIn(BaseModel):
    month: int
    score: float = 0.5
    water_temp_c_min: Optional[float] = None
    water_temp_c_max: Optional[float] = None
    visibility_m_typical: Optional[float] = None
    notes: Optional[str] = None
    highlights: list[str] = Field(default_factory=list)

    @field_validator("month")
    @classmethod
    def month_range(cls, v: int) -> int:
        if v < 1 or v > 12:
            raise ValueError("month must be 1–12")
        return v


class DiveSiteIn(BaseModel):
    """Normalized site payload every crawler adapter must emit."""

    slug: Optional[str] = None
    name: str
    aliases: list[str] = Field(default_factory=list)
    site_types: list[str] = Field(default_factory=list)
    water_type: str = "salt"
    entry_type: str = "unknown"
    skill_level: str = "unknown"
    region_slug: Optional[str] = None
    country_code: Optional[str] = None
    locality: Optional[str] = None
    description: Optional[str] = None
    depth_min_m: Optional[float] = None
    depth_max_m: Optional[float] = None
    typical_visibility_m: Optional[float] = None
    lon: float
    lat: float
    tags: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    properties: dict[str, Any] = Field(default_factory=dict)
    seasonality: list[SeasonalityIn] = Field(default_factory=list)
    # Provenance
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class DiveSiteOut(BaseModel):
    id: str
    slug: str
    name: str
    site_types: list[str]
    country_code: Optional[str]
    locality: Optional[str]
    lon: float
    lat: float
    depth_min_m: Optional[float]
    depth_max_m: Optional[float]
    skill_level: str
    confidence: float
    tags: list[str]

    model_config = {"from_attributes": True}
