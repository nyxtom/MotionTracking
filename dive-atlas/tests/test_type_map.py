from dive_atlas.ingest.type_map import normalize_site_types, osm_tags_to_types


def test_normalize_padi_types():
    assert "reef" in normalize_site_types("Reef", "Wall")
    assert "wreck" in normalize_site_types("Wreck")
    assert "cenote" in normalize_site_types("Cenote")


def test_osm_wreck_tags():
    types = osm_tags_to_types({"seamark:type": "wreck", "name": "SS Test"})
    assert "wreck" in types
