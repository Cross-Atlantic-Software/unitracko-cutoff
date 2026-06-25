"""CollegeDekho scraper.

Easy target: fully server-rendered Django HTML tables, no JSON blob, no anti-bot.
Current-year cutoffs at ``/exam/<slug>/cutoff``; historical years at
``/exam/<slug>/cutoff-<YEAR>-esp``. Wide category-column tables are melted to long
form by the shared toolkit; institute/year/round context lives in the preceding
headings (handled by ``headings_before_tables``).
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse

COMPETITOR = "collegedekho"
_EXAM_SLUG_RE = re.compile(r"^/exam/([^/?#]+)")
# Freshest four completed cycles, computed at import (e.g. 2025-2022 in 2026), so
# the latest year is never silently omitted as a hard-coded tuple would.
DEFAULT_YEARS = tuple(range(date.today().year - 1, date.today().year - 5, -1))


_DEFAULT_BASE = "https://www.collegedekho.com"


def _urls_from_slug(base: str, slug: str, years: tuple[int, ...]) -> list[str]:
    urls = [f"{base}/exam/{slug}/cutoff"]
    urls += [f"{base}/exam/{slug}/cutoff-{y}-esp" for y in years]
    return urls


def cutoff_urls(sheet_url: str, *, years: tuple[int, ...] = DEFAULT_YEARS,
                exam: str | None = None, **_: object) -> list[str]:
    """Current-year cutoff page plus the ``-<year>-esp`` archives.

    Falls back to candidate slugs derived from the search term / exam name when the
    path carries no ``/exam/<slug>`` (search-landing / course links).
    """
    from cutoffs.competitors._resolve import candidate_slugs, dedupe

    p = urlparse(sheet_url or "")
    base = f"{p.scheme}://{p.netloc}" if p.netloc else _DEFAULT_BASE
    m = _EXAM_SLUG_RE.match(p.path or "")
    if m:
        return _urls_from_slug(base, m.group(1), years)
    urls: list[str] = []
    for slug in candidate_slugs(sheet_url, exam):
        urls += _urls_from_slug(base, slug, years)
    return dedupe(urls)


def exam_slug(sheet_url: str) -> str | None:
    p = urlparse(sheet_url or "")
    m = _EXAM_SLUG_RE.match(p.path or "")
    return m.group(1) if m else None


def _slug_candidates(sheet_url: str, exam: str | None) -> list[str]:
    """The path slug (a single known-good value) or resolver-derived candidates."""
    path_slug = exam_slug(sheet_url)
    if path_slug:
        return [path_slug]
    from cutoffs.competitors._resolve import candidate_slugs

    return candidate_slugs(sheet_url, exam)


def scrape(sheet_url: str, exam: str, *, years: tuple[int, ...] = DEFAULT_YEARS,
           **_: object) -> list[dict]:
    from cutoffs.competitors._common import fetch_html, rows_from_tables
    from urllib.parse import urlparse

    p = urlparse(sheet_url or "")
    base = f"{p.scheme}://{p.netloc}" if p.netloc else _DEFAULT_BASE
    derived = exam_slug(sheet_url) is None

    rows: list[dict] = []
    for slug in _slug_candidates(sheet_url, exam):
        # Current-year page first. For a *derived* slug, only fan out to the year
        # archives when this page actually exists (non-empty html) — a wrong guess
        # then costs 1 GET, not 1 + len(years). A path slug is known-good, so it
        # always fetches the full archive set regardless.
        cur_url = f"{base}/exam/{slug}/cutoff"
        cur_html = fetch_html(cur_url, impersonate=False)
        if cur_html:
            rows += rows_from_tables(cur_html, competitor=COMPETITOR, exam=exam,
                                     slug=slug, page_url=cur_url,
                                     page_type="exam_cutoff", year=None)
        elif derived:
            continue  # slug didn't resolve — don't probe its archives
        for y in years:
            arch_url = f"{base}/exam/{slug}/cutoff-{y}-esp"
            html = fetch_html(arch_url, impersonate=False)
            if not html:
                continue
            rows += rows_from_tables(html, competitor=COMPETITOR, exam=exam,
                                     slug=slug, page_url=arch_url,
                                     page_type="exam_cutoff", year=str(y))
    return rows
