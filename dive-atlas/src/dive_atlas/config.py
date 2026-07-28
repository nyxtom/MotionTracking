from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DIVE_ATLAS_",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://dive:dive@localhost:5432/dive_atlas"
    log_level: str = "INFO"
    # Default radius (meters) when linking shops/operators via GIS later
    operator_enrichment_radius_m: int = 25_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
