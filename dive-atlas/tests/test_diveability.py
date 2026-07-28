from dive_atlas.ingest.diveability import (
    is_diveable_cave_name,
    is_diveable_wikidata_cave,
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
    # "dive" inside Diversion / Diversas; "sump" inside Bosumpra
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
