from dive_atlas.ingest import load_all_adapters, list_adapters, get_adapter
from dive_atlas.taxonomy import SiteType


def test_site_type_covers_core_atlas_surface():
    needed = {
        "reef",
        "wreck",
        "cave",
        "cenote",
        "atoll",
        "blue_hole",
        "wall",
        "spring",
        "cavern",
    }
    assert needed.issubset({t.value for t in SiteType})


def test_seed_adapter_loads_famous_sites():
    load_all_adapters()
    batch = get_adapter("seed-famous").fetch()
    assert len(batch.regions) >= 10
    assert len(batch.sites) >= 15
    types = {t for site in batch.sites for t in site.site_types}
    for required in ("cave", "cenote", "reef", "wreck", "atoll", "blue_hole", "spring"):
        assert required in types, f"missing {required} in seed corpus"
    # Coordinates sanity
    for site in batch.sites:
        assert -180 <= site.lon <= 180
        assert -90 <= site.lat <= 90


def test_adapters_registered():
    load_all_adapters()
    assert "seed-famous" in list_adapters()
    assert "seed-habitats" in list_adapters()
    assert "open-data-stub" in list_adapters()


def test_habitats_seed_flags_access():
    load_all_adapters()
    batch = get_adapter("seed-habitats").fetch()
    assert len(batch.sites) >= 2
    by_slug = {s.slug: s for s in batch.sites}
    aquarius = by_slug["us-aquarius-reef-base"]
    assert aquarius.diveable is True
    assert aquarius.access == "research_only"
    assert "habitat" in aquarius.tags
    jules = by_slug["padi-24374-jules-undersea-lab"]
    assert jules.diveable is True
    assert jules.access == "recreational"
    assert jules.description and "pizza" in jules.description.lower()


def test_access_kind_values():
    from dive_atlas.taxonomy import AccessKind

    assert AccessKind.RESEARCH_ONLY.value == "research_only"
    assert {a.value for a in AccessKind} >= {
        "recreational",
        "restricted",
        "research_only",
        "private",
        "closed",
        "unknown",
    }