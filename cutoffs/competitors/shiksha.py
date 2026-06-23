"""Shiksha scraper — the risk child.

Data is rich and server-rendered (easy to parse once fetched), but Shiksha sits
behind Akamai-style anti-bot that 403s every datacenter request. So fetch via
``curl_cffi`` (chrome TLS fingerprint) — and if that's unavailable or still
blocked, **degrade to empty + log** so it never blocks the rest of the pipeline.

URLs: the exam cutoff hub is ``/<stream>/<slug>-exam-cutoff`` (note the
``-exam-cutoff`` suffix, NOT ``/cutoff`` appended); the richest source is
``/college/<id>/cutoff`` (not built here — discovered at crawl time). Generic
``/search?q=`` landing links have no resolvable slug.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

COMPETITOR = "shiksha"
_DEFAULT_BASE = "https://www.shiksha.com"
# /<stream>/<slug>-exam  or  /<stream>/<slug>-exam-cutoff
_EXAM_RE = re.compile(r"^/([^/]+)/(.+?)-exam(?:-cutoff)?/?$")
# The cutoff hub lives under a stream segment we can't read off a /search link, so
# the fallback tries the most common streams. Kept short (and slugs capped) so a
# search-landing exam costs a handful of requests, not dozens, on this gated site.
_STREAMS = ("engineering", "medicine", "science", "management", "law")


def cutoff_urls(sheet_url: str, *, exam: str | None = None, **_: object) -> list[str]:
    """Build the ``-exam-cutoff`` hub URL.

    Prefers the exact ``/<stream>/<slug>`` in the path; for ``/search?q=`` landing
    links falls back to candidate slugs (derived from the search term / exam name)
    crossed with the common streams.
    """
    from cutoffs.competitors._resolve import candidate_slugs, dedupe

    p = urlparse(sheet_url or "")
    path = p.path or ""
    base = f"{p.scheme}://{p.netloc}" if p.netloc else _DEFAULT_BASE
    m = _EXAM_RE.match(path)
    if m:
        stream, slug = m.group(1), m.group(2)
        return [f"{base}/{stream}/{slug}-exam-cutoff"]
    urls: list[str] = []
    for slug in candidate_slugs(sheet_url, exam, max_slugs=2):
        for stream in _STREAMS:
            urls.append(f"{base}/{stream}/{slug}-exam-cutoff")
    return dedupe(urls)


def exam_slug(sheet_url: str) -> str | None:
    m = _EXAM_RE.match(urlparse(sheet_url or "").path or "")
    return m.group(2) if m else None


def scrape(sheet_url: str, exam: str, **_: object) -> list[dict]:
    from cutoffs.competitors._common import fetch_html, rows_from_tables

    slug = exam_slug(sheet_url) or ""
    rows: list[dict] = []
    for url in cutoff_urls(sheet_url, exam=exam):
        html = fetch_html(url, impersonate=True)  # Akamai: needs curl_cffi/chrome
        if not html:
            continue  # blocked / curl_cffi absent -> degrade to empty
        rows += rows_from_tables(html, competitor=COMPETITOR, exam=exam, slug=slug,
                                 page_url=url, page_type="exam_cutoff")
    return rows
