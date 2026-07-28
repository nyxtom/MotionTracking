from dive_atlas.ingest.diveability import (
    is_diveable_cave_name,
    is_diveable_wikidata_cave,
    is_indoor_pool_name,
    is_junk_wikidata_wreck_name,
    is_operator_name,
    is_osm_operator_tags,
)


def test_rejects_terrestrial_and_archaeology_caves():
    for name in (
        "Amud cave",
        "Tabun cave",
        "Kanheri Caves",
        "Seokguram",
        "Bontnewydd Palaeolithic site",
        "Grotto of Gethsemane",
        "Massabielle Grotto",
        "Cishansi Grottoes",
        "Maximiliansgrotte",
        "Notts Pot",
    ):
        assert not is_diveable_cave_name(name), name
        assert not is_diveable_wikidata_cave(
            name=name, class_qid="Q35509", class_label="cave"
        ), name


def test_rejects_substring_false_positives():
    for name in (
        "Arcadia Diversion Dam",
        "Abrigo de las Figuras Diversas",
        "Bosumpra Cave",
    ):
        assert not is_diveable_cave_name(name), name


def test_keeps_explicitly_diveable_cave_names():
    for name in (
        "Inazumi Underwater Cave",
        "Cenote Nohoch Nah Chich",
        "Sea Caves near Cape Greco",
        "St. Martins Sea Caves",
        "Swimming Hole Submerged Ocean Tunnel",
        "Blue Hole Cave",
        "Flooded Mine Sumps",
        "Cave Dive Training Site",
        "Diver's Cave",
    ):
        assert is_diveable_cave_name(name), name


def test_sea_cave_class_passes_without_keyword():
    assert is_diveable_wikidata_cave(
        name="Fingal's Cave", class_qid="Q1052919", class_label="sea cave"
    )
    assert is_diveable_wikidata_cave(
        name="Random Hole", class_qid="Q1051914", class_label="cenote"
    )


def test_rejects_canmore_and_unnamed_wrecks():
    for name in (
        "Unnamed Shipwreck - Canmore 102089",
        "Unknown 1791",
        "HMS Rhodesia (possibly)",
        "Q123456",
        "Canmore ID 999",
    ):
        assert is_junk_wikidata_wreck_name(name), name
    assert not is_junk_wikidata_wreck_name("USS Liberty")
    assert not is_junk_wikidata_wreck_name("Fujikawa Maru")


def test_osm_dive_centre_tags():
    assert is_osm_operator_tags({"tourism": "dive_centre", "name": "X"})
    assert is_osm_operator_tags({"amenity": "dive_centre"})
    assert is_osm_operator_tags({"shop": "scuba_diving"})
    assert is_osm_operator_tags({"amenity": "spring_board"})
    assert not is_osm_operator_tags({"sport": "scuba_diving", "name": "Blue Corner"})


def test_operator_and_pool_names():
    assert is_operator_name("Cebu Dive Center")
    assert is_operator_name("Centro de Buceo Mojacar")
    assert is_indoor_pool_name("Hallenbad in Balve")
    assert is_indoor_pool_name("Zwembad Almere Stad")
    assert not is_indoor_pool_name("La Piscine")
