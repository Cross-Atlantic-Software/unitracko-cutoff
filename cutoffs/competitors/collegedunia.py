"""CollegeDunia scraper.

Easy target: server-rendered Next.js HTML tables (no JS execution needed), gated
only by a User-Agent allowlist (bot UAs -> 403, browser UA -> 200). The exam-level
cutoff page is ``/exams/<slug>/cutoff``; deeper per-college tables live at
``/university/<id>-<slug>/cutoff`` (not built here — discovered at crawl time).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

COMPETITOR = "collegedunia"
_EXAM_SLUG_RE = re.compile(r"^/exams/([^/?#]+)")


def cutoff_urls(sheet_url: str, **_: object) -> list[str]:
    """Build the exam cutoff URL from a sheet landing URL.

    Returns [] for generic ``/e-search?term=`` or ``/courses/`` links that have no
    resolvable exam slug.
    """
    p = urlparse(sheet_url or "")
    m = _EXAM_SLUG_RE.match(p.path or "")
    if not m:
        return []
    slug = m.group(1)
    base = f"{p.scheme}://{p.netloc}"
    return [f"{base}/exams/{slug}/cutoff"]


def exam_slug(sheet_url: str) -> str | None:
    p = urlparse(sheet_url or "")
    m = _EXAM_SLUG_RE.match(p.path or "")
    return m.group(1) if m else None


def scrape(sheet_url: str, exam: str, **_: object) -> list[dict]:
    """Fetch the cutoff page(s) and return raw rows (heavy deps imported lazily)."""
    from cutoffs.competitors._common import fetch_html, rows_from_tables

    slug = exam_slug(sheet_url) or ""
    rows: list[dict] = []
    for url in cutoff_urls(sheet_url):
        html = fetch_html(url, impersonate=False)  # browser-UA httpx is enough
        if not html:
            continue
        rows += rows_from_tables(html, competitor=COMPETITOR, exam=exam, slug=slug,
                                 page_url=url, page_type="exam_cutoff")
    return rows
