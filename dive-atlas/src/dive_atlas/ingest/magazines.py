from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from dive_atlas.ingest.http_util import HttpFetcher
from dive_atlas.magazine_schemas import MagazineArticleIn, MagazineIssueIn, MagazineIn

REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "sources" / "dive_magazines.json"
)

# Lightweight place / site cue extraction across languages
_PLACE_PATTERNS = [
    re.compile(
        r"\b("
        r"Cozumel|Cenote\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\'\-]+|"
        r"Okinawa|Kerama|Ishigaki|Jeju|Seogwipo|"
        r"Raja\s+Ampat|Komodo|Bunaken|Sipadan|Similan|"
        r"Scapa\s+Flow|Truk|Chuuk|Thistlegorm|Yongala|"
        r"Blue\s+Hole|Great\s+Barrier\s+Reef|Bonaire|Maldives|"
        r"Red\s+Sea|Ras\s+Mohammed|Ginnie\s+Springs|Peacock\s+Springs|"
        r"Tulum|Playa\s+del\s+Carmen|Key\s+Largo|Monterey|"
        r"제주|오키나와|코즈멜|라자암파트"
        r")\b",
        re.I,
    ),
]

_ARTICLE_HREF = re.compile(
    r'href=["\']([^"\']+)["\'][^>]*>([^<]{8,160})<',
    re.I,
)
_DATE_IN_URL = re.compile(r"(20\d{2})[/-](\d{1,2})")
_ISSUE_HINT = re.compile(
    r"(issue|ausgabe|édition|edicion|호|号|magazin|magazine).*?(20\d{2})",
    re.I,
)


def load_magazine_registry(path: Path | None = None) -> list[MagazineIn]:
    data = json.loads((path or REGISTRY_PATH).read_text(encoding="utf-8"))
    out: list[MagazineIn] = []
    for raw in data.get("magazines", []):
        langs = list(raw.get("languages") or [])
        if raw.get("language") and raw["language"] not in langs:
            langs = [raw["language"], *langs]
        out.append(
            MagazineIn(
                slug=raw["slug"],
                name=raw["name"],
                name_local=raw.get("name_local"),
                language=raw.get("language") or "en",
                languages=langs,
                countries=raw.get("countries") or [],
                regions=raw.get("regions") or [],
                base_url=raw.get("base_url"),
                archive_url=raw.get("archive_url") or raw.get("base_url"),
                focus=raw.get("focus") or [],
                status=raw.get("status") or "unknown",
                priority=int(raw.get("priority") or 5),
                notes=raw.get("notes"),
                properties={"registry": True},
            )
        )
    return sorted(out, key=lambda m: (m.priority, m.slug))


def extract_place_mentions(*texts: str | None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        for pattern in _PLACE_PATTERNS:
            for m in pattern.finditer(text):
                val = re.sub(r"\s+", " ", m.group(1)).strip()
                key = val.lower()
                if key not in seen:
                    seen.add(key)
                    found.append(val)
    return found


def _same_host(base: str, href: str) -> bool:
    try:
        return urlparse(base).netloc == urlparse(href).netloc
    except Exception:  # noqa: BLE001
        return False


def _clean_text(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class MagazineWebCrawler:
    """Generic HTML archive crawler for a magazine homepage / archive URL.

    Discovers article-like links on the same host, fetches bodies, mines place
    mentions. Designed to run across years of web content; PDF/OCR issue
    pipelines plug in later per-publisher.
    """

    def __init__(
        self,
        magazine: MagazineIn,
        *,
        max_articles: int = 200,
        lookback_years: int = 15,
    ) -> None:
        self.magazine = magazine
        self.max_articles = max_articles
        self.lookback_years = lookback_years

    def crawl(self) -> tuple[list[MagazineIssueIn], list[MagazineArticleIn]]:
        start = self.magazine.archive_url or self.magazine.base_url
        if not start:
            return [], []
        issues: list[MagazineIssueIn] = []
        articles: list[MagazineArticleIn] = []
        with HttpFetcher(
            min_interval_s=0.35,
            timeout=45.0,
            headers={"Accept": "text/html,application/xhtml+xml"},
        ) as http:
            try:
                index_html = http.get_text(start)
            except Exception:  # noqa: BLE001
                return [], []
            candidates = self._discover_links(start, index_html)
            for href, link_text in candidates[: self.max_articles]:
                try:
                    html = http.get_text(href)
                except Exception:  # noqa: BLE001
                    continue
                body = _clean_text(html)
                if len(body) < 400:
                    continue
                title = self._extract_title(html) or link_text.strip()
                published = self._guess_date(href, html)
                if published and published.year < (date_today_year() - self.lookback_years):
                    continue
                places = extract_place_mentions(title, link_text, body[:8000])
                external_id = href.rstrip("/").rsplit("/", 1)[-1][:200] or href[-200:]
                articles.append(
                    MagazineArticleIn(
                        magazine_slug=self.magazine.slug,
                        external_id=external_id,
                        title=title[:500],
                        url=href,
                        published_on=published,
                        language=self.magazine.language,
                        summary=body[:400],
                        body_text=body[:50000],
                        place_mentions=places,
                        tags=list(self.magazine.focus),
                        confidence=0.55 if places else 0.35,
                        raw={"source": "html_archive", "link_text": link_text[:200]},
                    )
                )
                if _ISSUE_HINT.search(title) or _ISSUE_HINT.search(href):
                    issues.append(
                        MagazineIssueIn(
                            magazine_slug=self.magazine.slug,
                            external_id=f"issue-{external_id}"[:240],
                            title=title[:400],
                            year=published.year if published else None,
                            month=published.month if published else None,
                            published_on=published,
                            url=href,
                            language=self.magazine.language,
                            raw={"discovered_from": "article_hint"},
                        )
                    )
        return issues, articles

    def _discover_links(self, base: str, html: str) -> list[tuple[str, str]]:
        scored: list[tuple[int, str, str]] = []
        seen: set[str] = set()
        keywords = (
            "dive",
            "tauch",
            "plonge",
            "sub",
            "wreck",
            "reef",
            "cenote",
            "cave",
            "여행",
            "다이브",
            "ダイビング",
            "マリン",
            "issue",
            "article",
            "news",
            "travel",
            "site",
            "magazin",
            "blog",
            "story",
            "feature",
            "report",
            "destination",
            "ocean",
            "underwater",
            "post",
        )
        for href, text in _ARTICLE_HREF.findall(html):
            if href.startswith("#") or href.startswith("mailto:"):
                continue
            abs_url = urljoin(base, href)
            if not abs_url.startswith("http"):
                continue
            if not _same_host(base, abs_url):
                continue
            path = urlparse(abs_url).path.lower()
            if any(path.endswith(ext) for ext in (".jpg", ".png", ".css", ".js", ".zip", ".svg")):
                continue
            if abs_url.rstrip("/") == base.rstrip("/"):
                continue
            blob = f"{path} {text}".lower()
            score = sum(1 for k in keywords if k in blob)
            # Prefer deeper paths (likely articles) over bare sections
            score += min(path.count("/"), 4)
            if abs_url in seen:
                continue
            seen.add(abs_url)
            scored.append((score, abs_url, re.sub(r"\s+", " ", text).strip()))
        scored.sort(key=lambda x: (-x[0], x[1]))
        # Keep keyword hits first; if sparse, still take top same-host links
        strong = [(u, t) for s, u, t in scored if s >= 2]
        if len(strong) >= 10:
            return strong
        return [(u, t) for _, u, t in scored]

    def _extract_title(self, html: str) -> str | None:
        m = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html)
        if m:
            return _clean_text(m.group(1))[:500] or None
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
        if m:
            return _clean_text(m.group(1))[:500] or None
        return None

    def _guess_date(self, url: str, html: str):
        from datetime import date

        m = _DATE_IN_URL.search(url)
        if m:
            year, month = int(m.group(1)), int(m.group(2))
            month = min(max(month, 1), 12)
            try:
                return date(year, month, 1)
            except ValueError:
                return None
        m = re.search(
            r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})",
            html[:5000],
        )
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
        return None


def date_today_year() -> int:
    from datetime import date

    return date.today().year
