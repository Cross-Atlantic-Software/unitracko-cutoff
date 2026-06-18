"""Shared polite-fetch helper for adapters.

Every adapter that pulls a live page/PDF used to hand-roll the same
``httpx.get(url, headers=..., timeout=..., follow_redirects=True)`` +
``raise_for_status()`` and carry its own ``_HEADERS`` copy. This centralizes that
into one ``fetch`` with a realistic User-Agent, explicit connect/read timeouts,
and bounded retry/backoff (the project's "polite scraping" convention), so a
single transient blip no longer drops straight to cached.
"""

from __future__ import annotations

import logging
import time

import httpx

_log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def fetch(
    url: str,
    *,
    timeout: float = 30.0,
    retries: int = 1,
    backoff: float = 1.5,
) -> httpx.Response:
    """GET ``url`` politely and return the response, or raise after retries.

    ``timeout`` bounds the read; connect is capped at 10s so a dead host fails
    fast. On a transient error we retry ``retries`` times with linear backoff;
    the last exception propagates so callers keep their cached-fallback ``except``.
    """
    to = httpx.Timeout(timeout, connect=min(10.0, timeout))
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.get(url, headers=HEADERS, timeout=to, follow_redirects=True)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001 - retry then re-raise
            last = exc
            if attempt < retries:
                _log.debug("fetch retry %d/%d for %s: %s",
                           attempt + 1, retries, url, exc)
                time.sleep(backoff * (attempt + 1))
    assert last is not None
    raise last
