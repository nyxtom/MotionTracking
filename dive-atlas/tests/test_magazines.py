from dive_atlas.ingest.magazines import extract_place_mentions, load_magazine_registry


def test_registry_has_east_asia_and_cenote_titles():
    mags = load_magazine_registry()
    slugs = {m.slug for m in mags}
    assert "marine-diving-jp" in slugs
    assert "scuba-diver-kr" in slugs
    assert "espacio-profundo-mx" in slugs
    assert "tauchen-de" in slugs
    langs = {m.language for m in mags}
    for lang in ("ja", "ko", "es", "de", "pt", "en"):
        assert lang in langs


def test_place_mention_extraction():
    hits = extract_place_mentions(
        "Diving Cenote Dos Ojos near Tulum and later Cozumel walls; also Okinawa Kerama."
    )
    blob = " ".join(hits).lower()
    assert "cozumel" in blob
    assert "tulum" in blob or "cenote" in blob
    assert "okinawa" in blob or "kerama" in blob
