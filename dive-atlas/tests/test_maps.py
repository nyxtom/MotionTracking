from dive_atlas.viz.maps import PRESET_REGIONS, _auto_zoom, _latlon_to_tile


def test_presets_cover_requested_regions():
    assert "roatan" in PRESET_REGIONS
    assert "japan" in PRESET_REGIONS
    assert "okinawa" in PRESET_REGIONS


def test_tile_math_roundtrip_ish():
    x, y = _latlon_to_tile(16.3, -86.5, 10)
    assert 0 < x < 2**10
    assert 0 < y < 2**10
    z = _auto_zoom(16.2, -86.8, 16.45, -86.4)
    assert 8 <= z <= 13
