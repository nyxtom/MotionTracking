"""Parse GeoJSON / KML / GPX into bare name+lon+lat records for site ingest."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree as ET


@dataclass
class GeoPoint:
    name: str
    lon: float
    lat: float
    description: str | None = None
    properties: dict | None = None


def _strip_ns(xml: str) -> str:
    return re.sub(r'\sxmlns(?::\w+)?="[^"]+"', "", xml)


def parse_geojson_bytes(raw: bytes | str) -> list[GeoPoint]:
    data = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace"))
    features = data.get("features") if isinstance(data, dict) else None
    if features is None and isinstance(data, dict) and data.get("type") == "Feature":
        features = [data]
    if not features:
        return []
    out: list[GeoPoint] = []
    for feat in features:
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        if geom.get("type") != "Point":
            # MultiPoint / take first coord of LineString centroid-ish: skip non-points for now
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        name = (
            props.get("name")
            or props.get("Name")
            or props.get("title")
            or props.get("SITE_NAME")
            or props.get("site_name")
            or f"Point {lon:.4f},{lat:.4f}"
        )
        out.append(
            GeoPoint(
                name=str(name).strip(),
                lon=lon,
                lat=lat,
                description=props.get("description") or props.get("desc"),
                properties=dict(props),
            )
        )
    return out


def parse_kml_bytes(raw: bytes | str) -> list[GeoPoint]:
    text = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
    # KMZ is zip — handled by caller
    if text[:2] == "PK":
        return parse_kmz_bytes(raw if isinstance(raw, bytes) else raw.encode())
    root = ET.fromstring(_strip_ns(text))
    out: list[GeoPoint] = []
    for pm in root.iter("Placemark"):
        name = (pm.findtext("name") or "").strip()
        desc = pm.findtext("description")
        coords_el = pm.find(".//coordinates")
        if coords_el is None or not (coords_el.text or "").strip():
            continue
        # KML may list multiple tuples; take first
        first = (coords_el.text or "").strip().split()[0]
        parts = first.split(",")
        if len(parts) < 2:
            continue
        lon, lat = float(parts[0]), float(parts[1])
        if not name:
            name = f"Point {lon:.4f},{lat:.4f}"
        out.append(GeoPoint(name=name, lon=lon, lat=lat, description=desc))
    return out


def parse_kmz_bytes(raw: bytes) -> list[GeoPoint]:
    with zipfile.ZipFile(BytesIO(raw)) as zf:
        # Prefer doc.kml, else first .kml
        names = zf.namelist()
        kml_name = next((n for n in names if n.lower().endswith("doc.kml")), None)
        if kml_name is None:
            kml_name = next((n for n in names if n.lower().endswith(".kml")), None)
        if kml_name is None:
            return []
        return parse_kml_bytes(zf.read(kml_name))


def parse_gpx_bytes(raw: bytes | str) -> list[GeoPoint]:
    text = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
    root = ET.fromstring(_strip_ns(text))
    out: list[GeoPoint] = []
    for tag in ("wpt", "trkpt"):
        for el in root.iter(tag):
            lat = el.attrib.get("lat")
            lon = el.attrib.get("lon")
            if lat is None or lon is None:
                continue
            name = (el.findtext("name") or "").strip() or f"Point {float(lon):.4f},{float(lat):.4f}"
            out.append(
                GeoPoint(
                    name=name,
                    lon=float(lon),
                    lat=float(lat),
                    description=el.findtext("desc"),
                )
            )
    return out


def parse_bytes(raw: bytes, *, fmt: str) -> list[GeoPoint]:
    fmt = fmt.lower().strip()
    if fmt in {"geojson", "json"}:
        return parse_geojson_bytes(raw)
    if fmt in {"kml"}:
        return parse_kml_bytes(raw)
    if fmt in {"kmz"}:
        return parse_kmz_bytes(raw)
    if fmt in {"gpx"}:
        return parse_gpx_bytes(raw)
    raise ValueError(f"Unsupported geo format: {fmt}")
