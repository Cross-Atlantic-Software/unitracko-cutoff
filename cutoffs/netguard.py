"""SSRF guard + polite-fetch helpers shared by the live fetchers.

Centralizes three things CLAUDE.md (polite scraping) and the security audit require
but that the fetchers were missing:

1. **SSRF guard** — only ``http(s)`` URLs whose host resolves to a PUBLIC address
   are fetched, re-validated on EVERY redirect hop, so a search-result link (cat-3
   feeds in arbitrary DuckDuckGo result URLs) can't pivot to cloud metadata
   (``169.254.169.254``), ``localhost``, or a private/internal range.
2. **Politeness** — per-host request spacing with randomized jitter.
3. **Response-size cap** — a giant body can't exhaust memory.

Pure standard library except for the httpx client injected into ``fetch_validated``,
so the URL guard and throttle are unit-testable without a network.
"""
from __future__ import annotations

import ipaddress
import random
import socket
import time
from urllib.parse import urljoin, urlparse

MAX_BYTES = 30 * 1024 * 1024        # 30 MB response cap
MAX_REDIRECTS = 5
MIN_HOST_INTERVAL = 1.0             # min seconds between requests to the same host
JITTER = (0.3, 1.2)                 # extra randomized delay (seconds), per request

# host -> monotonic timestamp of its last request, for per-host spacing.
_LAST_REQUEST: dict[str, float] = {}


def _host_is_public(host: str) -> bool:
    """False if ``host`` is empty, a localhost alias, or resolves to any
    private / loopback / link-local / reserved / multicast address."""
    if not host or host.lower() in {"localhost", "localhost.localdomain", "ip6-localhost"}:
        return False
    try:
        candidates = [ipaddress.ip_address(host)]            # already an IP literal
    except ValueError:
        try:
            candidates = [ipaddress.ip_address(info[4][0])
                          for info in socket.getaddrinfo(host, None)]
        except (OSError, ValueError):
            return False                                     # unresolvable -> block
    if not candidates:
        return False
    return all(
        not (ip.is_private or ip.is_loopback or ip.is_link_local
             or ip.is_reserved or ip.is_multicast or ip.is_unspecified)
        for ip in candidates
    )


def is_safe_url(url: str) -> bool:
    """True only for an ``http(s)`` URL whose host resolves to a public address."""
    try:
        p = urlparse(url or "")
    except (ValueError, AttributeError):
        return False
    return p.scheme in ("http", "https") and _host_is_public(p.hostname or "")


def throttle(host: str) -> None:
    """Polite per-host spacing (``MIN_HOST_INTERVAL``) plus randomized jitter."""
    if host:
        last = _LAST_REQUEST.get(host)
        if last is not None:
            gap = MIN_HOST_INTERVAL - (time.monotonic() - last)
            if gap > 0:
                time.sleep(gap)
    lo, hi = JITTER
    if hi > 0:
        time.sleep(random.uniform(lo, hi))
    if host:
        _LAST_REQUEST[host] = time.monotonic()


def fetch_validated(client, url: str, *, follow_redirects: bool = True,
                    max_bytes: int = MAX_BYTES) -> tuple[int | None, str]:
    """Stream a GET through ``client`` (httpx), validating every redirect hop and
    capping the body. Returns ``(status_code, text)``; ``(None, "")`` on an SSRF
    block, a missing redirect target, or too many hops.

    ``client`` MUST be created with ``follow_redirects=False`` so hops pass through
    here (otherwise httpx auto-follows and the per-hop SSRF check is bypassed).
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if not is_safe_url(current):
            return (None, "")
        throttle(urlparse(current).hostname or "")
        with client.stream("GET", current) as resp:
            if resp.is_redirect and follow_redirects:
                loc = resp.headers.get("location", "")
                if not loc:
                    return (resp.status_code, "")
                current = urljoin(current, loc)
                continue
            if resp.status_code != 200:
                return (resp.status_code, "")
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    break
                chunks.append(chunk)
            return (200, b"".join(chunks).decode(resp.encoding or "utf-8", "replace"))
    return (None, "")  # exceeded MAX_REDIRECTS
