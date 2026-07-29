from dive_atlas.ingest.geo_files import parse_geojson_bytes, parse_kml_bytes, parse_gpx_bytes


def test_parse_geojson_points():
    raw = b"""
    {"type":"FeatureCollection","features":[
      {"type":"Feature","geometry":{"type":"Point","coordinates":[-86.6,16.3]},
       "properties":{"name":"Blue Channel"}}
    ]}
    """
    pts = parse_geojson_bytes(raw)
    assert len(pts) == 1
    assert pts[0].name == "Blue Channel"
    assert abs(pts[0].lon + 86.6) < 1e-6


def test_parse_kml_placemark():
    raw = b"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document>
      <Placemark><name>MARY'S PLACE</name>
        <Point><coordinates>-86.55,16.30,0</coordinates></Point>
      </Placemark>
    </Document></kml>
    """
    pts = parse_kml_bytes(raw)
    assert len(pts) == 1
    assert pts[0].name == "MARY'S PLACE"
    assert abs(pts[0].lat - 16.30) < 1e-6


def test_parse_gpx_wpt():
    raw = b"""<?xml version="1.0"?>
    <gpx><wpt lat="24.5" lon="-81.7"><name>Molasses Reef</name></wpt></gpx>
    """
    pts = parse_gpx_bytes(raw)
    assert len(pts) == 1
    assert pts[0].name == "Molasses Reef"
