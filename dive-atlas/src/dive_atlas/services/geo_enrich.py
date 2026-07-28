"""Geo enrichment: fill country_code + locality from URLs, dive-area bboxes, coords.

PADI/OSM often give points without ISO country or island locality. Coordinates
(+ travel URLs) are enough to backfill the rest.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from dive_atlas.models import DiveSite, SourceRecord


# PADI / common slug → ISO 3166-1 alpha-2
COUNTRY_SLUGS: dict[str, str] = {
    "honduras": "HN",
    "mexico": "MX",
    "belize": "BZ",
    "guatemala": "GT",
    "united-states": "US",
    "united-states-of-america-usa": "US",
    "united-states-virgin-islands": "VI",
    "british-virgin-islands": "VG",
    "canada": "CA",
    "japan": "JP",
    "south-korea": "KR",
    "korea": "KR",
    "indonesia": "ID",
    "thailand": "TH",
    "philippines": "PH",
    "malaysia": "MY",
    "maldives": "MV",
    "egypt": "EG",
    "australia": "AU",
    "new-zealand": "NZ",
    "fiji": "FJ",
    "micronesia": "FM",
    "federated-states-of-micronesia": "FM",
    "palau": "PW",
    "spain": "ES",
    "france": "FR",
    "italy": "IT",
    "greece": "GR",
    "croatia": "HR",
    "malta": "MT",
    "united-kingdom": "GB",
    "scotland": "GB",
    "ireland": "IE",
    "norway": "NO",
    "sweden": "SE",
    "netherlands": "NL",
    "germany": "DE",
    "portugal": "PT",
    "brazil": "BR",
    "colombia": "CO",
    "costa-rica": "CR",
    "panama": "PA",
    "nicaragua": "NI",
    "cuba": "CU",
    "jamaica": "JM",
    "bahamas": "BS",
    "cayman-islands": "KY",
    "turks-and-caicos": "TC",
    "turks-and-caicos-islands": "TC",
    "dominican-republic": "DO",
    "puerto-rico": "PR",
    "bonaire": "BQ",
    "curacao": "CW",
    "aruba": "AW",
    "sint-maarten": "SX",
    "st-maarten": "SX",
    "saint-lucia": "LC",
    "barbados": "BB",
    "trinidad-and-tobago": "TT",
    "south-africa": "ZA",
    "mozambique": "MZ",
    "tanzania": "TZ",
    "kenya": "KE",
    "sudan": "SD",
    "jordan": "JO",
    "israel": "IL",
    "turkey": "TR",
    "cyprus": "CY",
    "iceland": "IS",
    "papua-new-guinea": "PG",
    "solomon-islands": "SB",
    "vanuatu": "VU",
    "new-caledonia": "NC",
    "french-polynesia": "PF",
    "guam": "GU",
    "northern-mariana-islands": "MP",
    "taiwan": "TW",
    "china": "CN",
    "hong-kong": "HK",
    "vietnam": "VN",
    "cambodia": "KH",
    "myanmar": "MM",
    "sri-lanka": "LK",
    "india": "IN",
    "oman": "OM",
    "uae": "AE",
    "united-arab-emirates": "AE",
    "saudi-arabia": "SA",
    "red-sea": "EG",
    "seychelles": "SC",
    "mauritius": "MU",
    "madagascar": "MG",
    "ecuador": "EC",
    "galapagos": "EC",
    "peru": "PE",
    "chile": "CL",
    "argentina": "AR",
    "antarctica": "AQ",
    "samoa": "WS",
    "american-samoa": "AS",
    "tonga": "TO",
    "cook-islands": "CK",
    "marshall-islands": "MH",
    "kiribati": "KI",
    "tuvalu": "TV",
    "nauru": "NR",
    "east-timor": "TL",
    "timor-leste": "TL",
    "brunei": "BN",
    "singapore": "SG",
    "montenegro": "ME",
    "albania": "AL",
    "slovenia": "SI",
    "tunisia": "TN",
    "morocco": "MA",
    "canary-islands": "ES",
    "azores": "PT",
    "madeira": "PT",
}


@dataclass(frozen=True)
class DiveArea:
    name: str
    country_code: str
    south: float
    west: float
    north: float
    east: float
    aliases: tuple[str, ...] = ()


# Named dive localities — most-specific bbox wins (sorted by area at match time)
DIVE_AREAS: list[DiveArea] = [
    # Bay Islands / Honduras
    DiveArea("Roatán", "HN", 16.20, -86.80, 16.45, -86.35, ("roatan", "roatán", "roatán")),
    DiveArea("Utila", "HN", 16.05, -87.05, 16.15, -86.85, ("utila",)),
    DiveArea("Guanaja", "HN", 16.40, -86.00, 16.55, -85.80, ("guanaja",)),
    DiveArea("Bay Islands", "HN", 15.90, -87.20, 16.60, -85.70, ("bay islands", "islas de la bahia")),
    # Mexico / Belize
    DiveArea("Cozumel", "MX", 20.20, -87.10, 20.60, -86.70, ("cozumel",)),
    DiveArea("Tulum Cenotes", "MX", 20.05, -87.60, 20.45, -87.30, ("tulum",)),
    DiveArea("Playa del Carmen", "MX", 20.55, -87.15, 20.70, -87.00),
    DiveArea("Cancún / Isla Mujeres", "MX", 21.00, -86.95, 21.30, -86.70),
    DiveArea("Banco Chinchorro", "MX", 18.40, -87.50, 18.80, -87.20),
    DiveArea("Belize Barrier / Lighthouse", "BZ", 16.90, -88.20, 17.80, -87.30),
    DiveArea("Turneffe / Ambergris", "BZ", 17.80, -88.10, 18.20, -87.80),
    # Dutch Caribbean / Lesser Antilles
    DiveArea("Bonaire", "BQ", 12.00, -68.45, 12.35, -68.15, ("bonaire",)),
    DiveArea("Curaçao", "CW", 12.00, -69.20, 12.40, -68.70),
    DiveArea("Aruba", "AW", 12.40, -70.10, 12.65, -69.85),
    DiveArea("Saba", "BQ", 17.60, -63.30, 17.68, -63.20),
    DiveArea("St. Eustatius", "BQ", 17.46, -63.00, 17.52, -62.94),
    DiveArea("Tobago", "TT", 11.10, -60.90, 11.40, -60.45),
    # Cayman / Bahamas / Cuba
    DiveArea("Grand Cayman", "KY", 19.25, -81.45, 19.40, -81.15),
    DiveArea("Little Cayman", "KY", 19.65, -80.15, 19.72, -79.95),
    DiveArea("Cayman Brac", "KY", 19.68, -79.90, 19.75, -79.70),
    DiveArea("Nassau / New Providence", "BS", 24.95, -77.60, 25.15, -77.20),
    DiveArea("Exuma Cays", "BS", 23.40, -76.20, 24.60, -75.80),
    DiveArea("Jardines de la Reina", "CU", 20.70, -79.50, 21.40, -78.20),
    # Florida / US
    DiveArea("Key Largo", "US", 24.95, -80.55, 25.25, -80.20),
    DiveArea("Florida Keys", "US", 24.40, -82.00, 25.20, -80.20),
    DiveArea("North Florida Springs", "US", 29.50, -84.00, 30.50, -82.00),
    DiveArea("Monterey / California", "US", 36.40, -122.10, 36.90, -121.80),
    DiveArea("Catalina Island", "US", 33.30, -118.60, 33.50, -118.30),
    DiveArea("Hawaii Big Island", "US", 18.90, -156.10, 20.30, -154.80),
    DiveArea("Maui / Molokini", "US", 20.55, -156.70, 21.05, -155.90),
    DiveArea("Oahu", "US", 21.20, -158.30, 21.75, -157.60),
    # Japan / Korea
    DiveArea("Kerama", "JP", 26.10, 127.15, 26.30, 127.45, ("kerama", "zamami")),
    DiveArea("Okinawa Main Island", "JP", 26.05, 127.60, 26.90, 128.35, ("okinawa", "naha", "onna")),
    DiveArea("Ishigaki / Yaeyama", "JP", 24.20, 123.90, 24.60, 124.40, ("ishigaki", "kabira", "yaeyama")),
    DiveArea("Miyako", "JP", 24.70, 125.10, 24.95, 125.50, ("miyako",)),
    DiveArea("Izu / Osezaki", "JP", 34.70, 138.70, 35.20, 139.20),
    DiveArea("Jeju / Seogwipo", "KR", 33.10, 126.15, 33.55, 126.95, ("jeju", "seogwipo")),
    # Indonesia / SE Asia
    DiveArea("Raja Ampat", "ID", -2.85, 129.35, 0.95, 132.05, ("raja ampat", "raja-ampat")),
    DiveArea("Dampier Strait", "ID", -0.75, 130.40, -0.35, 130.90, ("dampier", "kri", "mansuar", "arborek")),
    DiveArea("Fam / Penemu", "ID", -0.70, 130.15, -0.45, 130.40, ("fam", "penemu", "melissa")),
    DiveArea("Misool", "ID", -2.45, 129.55, -1.85, 131.10, ("misool", "boo", "fiabacet")),
    DiveArea("Wayag / Kawe", "ID", 0.05, 130.00, 0.55, 130.55, ("wayag", "kawe")),
    DiveArea("Batanta", "ID", -0.95, 130.40, -0.70, 130.85, ("batanta",)),
    DiveArea("Komodo", "ID", -8.90, 119.20, -8.20, 119.90),
    DiveArea("Bali", "ID", -8.90, 114.40, -8.05, 115.80),
    DiveArea("Nusa Penida", "ID", -8.85, 115.40, -8.65, 115.75),
    DiveArea("Bunaken / Manado", "ID", 1.40, 124.60, 1.80, 125.00),
    DiveArea("Lembeh", "ID", 1.40, 125.15, 1.55, 125.30),
    DiveArea("Wakatobi", "ID", -5.90, 123.50, -5.20, 124.20),
    DiveArea("Banda Sea", "ID", -5.50, 129.00, -3.50, 132.00),
    DiveArea("Sipadan / Mabul", "MY", 4.05, 118.50, 4.30, 118.75),
    DiveArea("Tioman", "MY", 2.70, 104.05, 2.90, 104.25),
    DiveArea("Similan / Richelieu", "TH", 8.40, 97.50, 9.50, 98.10),
    DiveArea("Koh Tao", "TH", 10.00, 99.75, 10.20, 99.90),
    DiveArea("Koh Phi Phi", "TH", 7.65, 98.70, 7.80, 98.85),
    DiveArea("Coron / Busuanga", "PH", 11.80, 119.90, 12.20, 120.40),
    DiveArea("Puerto Galera", "PH", 13.45, 120.90, 13.55, 121.00),
    DiveArea("Apo Island / Dauin", "PH", 9.00, 123.00, 9.20, 123.40),
    DiveArea("Malapascua", "PH", 11.30, 124.05, 11.40, 124.15),
    # Maldives / Indian Ocean / Red Sea
    DiveArea("Maldives Central", "MV", 1.50, 72.80, 5.50, 73.80),
    DiveArea("Ari Atoll", "MV", 3.20, 72.60, 4.20, 73.00),
    DiveArea("Baa Atoll", "MV", 4.80, 72.70, 5.40, 73.20),
    DiveArea("Sharm / Ras Mohammed", "EG", 27.60, 34.00, 28.10, 34.50),
    DiveArea("Hurghada", "EG", 26.80, 33.70, 27.60, 34.20),
    DiveArea("Dahab", "EG", 28.40, 34.45, 28.55, 34.60),
    DiveArea("Brothers / Daedalus", "EG", 24.80, 34.80, 26.50, 35.20),
    DiveArea("Sodwana Bay", "ZA", -27.60, 32.60, -27.30, 32.80),
    DiveArea("Aliwal Shoal", "ZA", -30.35, 30.75, -30.15, 30.95),
    # Pacific / Micronesia / Australia
    DiveArea("Chuuk / Truk Lagoon", "FM", 7.20, 151.60, 7.60, 152.10, ("truk", "chuuk")),
    DiveArea("Palau Rock Islands", "PW", 7.00, 134.10, 7.50, 134.60),
    DiveArea("Yap", "FM", 9.40, 138.00, 9.70, 138.30),
    DiveArea("Great Barrier Reef - Cairns", "AU", -17.20, 145.80, -16.00, 146.80),
    DiveArea("Yongala / Townsville", "AU", -19.50, 146.80, -18.80, 147.80),
    DiveArea("Ningaloo", "AU", -23.50, 113.40, -21.50, 114.20),
    DiveArea("Port Lincoln / Neptune", "AU", -35.20, 135.80, -34.60, 136.40),
    DiveArea("Poor Knights", "NZ", -35.55, 174.70, -35.40, 174.80),
    DiveArea("Galápagos", "EC", -1.50, -92.00, 1.50, -89.00, ("galapagos",)),
    DiveArea("Fiji Bligh Water", "FJ", -17.80, 177.50, -16.50, 179.50),
    DiveArea("Kimbe Bay", "PG", -5.60, 150.00, -5.20, 150.50),
    # Med / Europe
    DiveArea("Scapa Flow", "GB", 58.80, -3.30, 58.98, -2.70, ("scapa",)),
    DiveArea("Gozo / Malta", "MT", 35.80, 14.15, 36.10, 14.60),
    DiveArea("Croatia Adriatic", "HR", 42.40, 15.50, 45.20, 17.20),
    DiveArea("Red Sea Aqaba", "JO", 29.30, 34.90, 29.55, 35.05),
]


# Coarse country envelopes used only when URL + dive-area miss (largest areas last preference)
COUNTRY_BBOXES: list[DiveArea] = [
    DiveArea("Honduras", "HN", 12.90, -89.40, 16.60, -83.00),
    DiveArea("Belize", "BZ", 15.85, -89.30, 18.50, -87.40),
    DiveArea("Mexico Caribbean", "MX", 18.00, -88.50, 21.80, -86.50),
    DiveArea("Costa Rica", "CR", 8.00, -87.10, 11.30, -82.50),
    DiveArea("Panama", "PA", 7.00, -83.10, 9.70, -77.10),
    DiveArea("Colombia Caribbean", "CO", 8.00, -77.50, 12.60, -71.00),
    DiveArea("Cuba", "CU", 19.70, -85.00, 23.30, -74.00),
    DiveArea("Jamaica", "JM", 17.65, -78.40, 18.55, -76.15),
    DiveArea("Bahamas", "BS", 20.90, -79.50, 27.30, -72.50),
    DiveArea("Florida / SE US", "US", 24.30, -87.70, 31.00, -79.80),
    DiveArea("Egypt Red Sea", "EG", 22.00, 32.00, 31.70, 37.00),
    DiveArea("Indonesia", "ID", -11.20, 95.00, 6.20, 141.00),
    DiveArea("Philippines", "PH", 4.50, 116.80, 21.20, 127.00),
    DiveArea("Thailand", "TH", 5.50, 97.20, 20.50, 105.70),
    DiveArea("Malaysia", "MY", 0.80, 99.50, 7.50, 119.40),
    DiveArea("Maldives", "MV", -0.90, 72.50, 7.20, 73.80),
    DiveArea("Japan", "JP", 24.00, 122.80, 45.60, 146.00),
    DiveArea("South Korea", "KR", 33.00, 124.50, 38.70, 132.00),
    DiveArea("Australia", "AU", -44.00, 112.00, -10.00, 154.00),
    DiveArea("New Zealand", "NZ", -47.50, 166.00, -34.00, 179.00),
    DiveArea("Fiji", "FJ", -21.20, 176.80, -12.40, -178.00),  # note: dateline awkward
    DiveArea("Micronesia", "FM", 1.00, 137.00, 10.00, 163.00),
    DiveArea("Palau", "PW", 2.80, 131.00, 8.20, 134.80),
    DiveArea("Papua New Guinea", "PG", -12.00, 140.80, -1.00, 160.00),
    DiveArea("Greece", "GR", 34.70, 19.30, 41.80, 29.70),
    DiveArea("Croatia", "HR", 42.30, 13.40, 46.60, 19.50),
    DiveArea("Italy", "IT", 36.60, 6.60, 47.10, 18.60),
    DiveArea("Spain", "ES", 35.90, -9.40, 43.80, 4.40),
    DiveArea("France", "FR", 41.30, -5.20, 51.20, 9.60),
    DiveArea("United Kingdom", "GB", 49.80, -8.70, 60.90, 1.80),
    DiveArea("Malta", "MT", 35.78, 14.18, 36.10, 14.58),
    DiveArea("South Africa", "ZA", -35.00, 16.40, -22.00, 33.00),
    DiveArea("Brazil", "BR", -33.80, -53.20, 5.30, -32.30),
    DiveArea("Ecuador / Galápagos", "EC", -5.00, -92.10, 1.70, -75.00),
]


_VAGUE_LOCALITIES = {
    None,
    "",
    "honduras",
    "mexico",
    "japan",
    "indonesia",
    "egypt",
    "australia",
    "thailand",
    "malaysia",
    "philippines",
    "fiji",
    "brazil",
    "colombia",
    "cuba",
    "jamaica",
    "bahamas",
    "greece",
    "croatia",
    "italy",
    "spain",
    "france",
    "yucatan_carib",
    "okinawa_japan",
    "florida",
    "caribbean",
    "micronesia_truk",
    "uk_scapa",
    "lesser_antilles",
    "indonesia_west",
    "indonesia_east",
    "thailand_malaysia",
    "australia_east",
    "png_solomons",
    "med_west",
    "med_east",
    "red_sea",
    "korea",
    "hawaii",
    "california",
    "maldives",
    "south_africa",
    "raja ampat",  # allow sub-locality upgrade to Dampier/Misool/Wayag
}


def country_from_padi_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = [p for p in url.replace("https://travel.padi.com", "").strip("/").split("/") if p]
    if len(parts) >= 2 and parts[0] in {"dive-site", "dive-sites"}:
        return COUNTRY_SLUGS.get(parts[1].lower())
    return None


def area_for_point(lat: float, lon: float) -> DiveArea | None:
    hits = [
        a
        for a in DIVE_AREAS
        if a.south <= lat <= a.north and a.west <= lon <= a.east
    ]
    if not hits:
        return None
    hits.sort(key=lambda a: (a.north - a.south) * (a.east - a.west))
    return hits[0]


def country_bbox_for_point(lat: float, lon: float) -> DiveArea | None:
    hits = [
        a
        for a in COUNTRY_BBOXES
        if a.south <= lat <= a.north and a.west <= lon <= a.east
    ]
    if not hits:
        return None
    hits.sort(key=lambda a: (a.north - a.south) * (a.east - a.west))
    return hits[0]


def enrich_sites_geo(session: Session, *, limit: int | None = None) -> dict[str, int]:
    """Backfill country_code and locality for sites missing them."""
    stmt = select(DiveSite)
    if limit:
        stmt = stmt.limit(limit)
    sites = list(session.scalars(stmt).all())

    url_by_site: dict[str, str] = {}
    for sid, url in session.execute(
        select(SourceRecord.site_id, SourceRecord.external_url).where(
            SourceRecord.site_id.is_not(None),
            SourceRecord.external_url.is_not(None),
        )
    ):
        if sid and url:
            key = str(sid)
            if key not in url_by_site:
                url_by_site[key] = url

    coords = {
        str(row["id"]): (float(row["lat"]), float(row["lon"]))
        for row in session.execute(
            text(
                """
                SELECT id,
                       ST_Y(geom::geometry) AS lat,
                       ST_X(geom::geometry) AS lon
                FROM dive_sites
                """
            )
        ).mappings()
    }

    updated_country = 0
    updated_locality = 0
    tagged_area = 0

    for site in sites:
        latlon = coords.get(str(site.id))
        if not latlon:
            continue
        lat, lon = latlon

        if not site.country_code:
            cc = country_from_padi_url(url_by_site.get(str(site.id)))
            if not cc:
                area = area_for_point(lat, lon)
                if area:
                    cc = area.country_code
            if not cc:
                bbox = country_bbox_for_point(lat, lon)
                if bbox:
                    cc = bbox.country_code
            if cc:
                site.country_code = cc
                updated_country += 1

        area = area_for_point(lat, lon)
        if area:
            tagged_area += 1
            cur = (site.locality or "").strip().lower()
            if (
                cur in _VAGUE_LOCALITIES
                or cur.replace(" ", "-") in COUNTRY_SLUGS
                or not site.locality
            ):
                if site.locality != area.name:
                    site.locality = area.name
                    updated_locality += 1

            if not site.country_code:
                site.country_code = area.country_code
                updated_country += 1

            tags = list(site.tags or [])
            for alias in (area.name.lower(), *area.aliases):
                if alias and alias not in {t.lower() for t in tags}:
                    tags.append(alias)
            if "geo-enriched" not in tags:
                tags.append("geo-enriched")
            site.tags = tags
        elif not site.country_code:
            bbox = country_bbox_for_point(lat, lon)
            if bbox:
                site.country_code = bbox.country_code
                updated_country += 1

    session.flush()
    return {
        "scanned": len(sites),
        "country_set": updated_country,
        "locality_set": updated_locality,
        "area_matched": tagged_area,
    }
