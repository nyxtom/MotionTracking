"""One-shot: add diveable/access columns + flag cold-water coral points."""

from __future__ import annotations

from sqlalchemy import text

from dive_atlas.db import get_engine


def main() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE dive_sites
                  ADD COLUMN IF NOT EXISTS diveable boolean NOT NULL DEFAULT true,
                  ADD COLUMN IF NOT EXISTS access varchar(40) NOT NULL DEFAULT 'recreational'
                """
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_dive_sites_diveable ON dive_sites (diveable)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_dive_sites_access ON dive_sites (access)")
        )
        result = conn.execute(
            text(
                """
                UPDATE dive_sites
                SET diveable = false, access = 'unknown'
                WHERE tags @> ARRAY['cold-water-coral']::varchar[]
                  AND diveable IS DISTINCT FROM false
                """
            )
        )
        print(f"cold_water_flagged={result.rowcount}")
    print("migrated")


if __name__ == "__main__":
    main()
