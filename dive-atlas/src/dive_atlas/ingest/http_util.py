from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_HEADERS = {
    "User-Agent": "DiveAtlas/0.1 (+https://github.com/nyxtom; dive site research crawler)",
    "Accept": "application/json,text/plain,*/*",
}


class HttpFetcher:
    def __init__(
        self,
        *,
        timeout: float = 60.0,
        min_interval_s: float = 0.2,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={**DEFAULT_HEADERS, **(headers or {})},
            follow_redirects=True,
        )
        self._min_interval = min_interval_s
        self._last = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpFetcher:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last = time.monotonic()

    def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        last_err: Exception | None = None
        for attempt in range(5):
            self._throttle()
            try:
                resp = self._client.get(url, params=params)
                if resp.status_code in {429, 502, 503, 504}:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001 — retry then raise
                last_err = exc
                time.sleep(1.2 * (attempt + 1))
        assert last_err is not None
        raise last_err

    def get_text(self, url: str, *, params: dict[str, Any] | None = None) -> str:
        self._throttle()
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.text

    def get_bytes(self, url: str, *, params: dict[str, Any] | None = None) -> bytes:
        self._throttle()
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.content
