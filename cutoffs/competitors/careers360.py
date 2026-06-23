"""Careers360 scraper.

Medium target: no anti-bot, but cutoffs live in editorial articles at
``/articles/<slug>-cutoff`` (or ``-cut-off``) on an exam-specific *vertical*
subdomain (``medicine.`` / ``engineering.`` / ``law.`` / ``www.``), NOT at
``/exams/<slug>/cutoff`` (that 404s). The richest source is the
``window.INITIAL_STATE`` JSON which embeds the full article HTML (every table),
double-escaped; we prefer it and fall back to the rendered DOM tables.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

COMPETITOR = "careers360"
_DEFAULT_BASE = "https://www.careers360.com"
_SLUG_RE = re.compile(r"^/(?:exams|articles)/([^/?#]+)")


def _slug(path: str) -> str | None:
    m = _SLUG_RE.match(path or "")
    if not m:
        return None
    # Strip a trailing -cutoff/-cut-off so an article URL yields the bare slug.
    return re.sub(r"-cut-?off$", "", m.group(1))


def _urls_from_slug(base: str, slug: str) -> list[str]:
    return [f"{base}/articles/{slug}-cutoff", f"{base}/articles/{slug}-cut-off"]


def cutoff_urls(sheet_url: str, *, exam: str | None = None, **_: object) -> list[str]:
    """Article cutoff URLs on the same vertical subdomain (both -cutoff variants).

    Falls back to candidate slugs derived from the search term / exam name when the
    path carries no ``/exams|/articles`` slug. The vertical subdomain stays whatever
    the link used (``www`` redirects to the right one), so we don't fan across all
    verticals — keeping the candidate count polite.
    """
    from cutoffs.competitors._resolve import candidate_slugs, dedupe

    p = urlparse(sheet_url or "")
    base = f"{p.scheme}://{p.netloc}" if p.netloc else _DEFAULT_BASE
    slug = _slug(p.path or "")
    if slug:
        return _urls_from_slug(base, slug)
    urls: list[str] = []
    for cand in candidate_slugs(sheet_url, exam):
        urls += _urls_from_slug(base, cand)
    return dedupe(urls)


def exam_slug(sheet_url: str) -> str | None:
    return _slug(urlparse(sheet_url or "").path or "")


def _article_html_from_state(state: dict) -> str | None:
    """Best-effort dig the article body HTML out of window.INITIAL_STATE."""
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if (isinstance(val, str) and key.lower() in {"content", "body", "html", "description"}
                        and "<table" in val.lower()):
                    found.append(val)
                else:
                    walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(state)
    return max(found, key=len) if found else None


def scrape(sheet_url: str, exam: str, **_: object) -> list[dict]:
    from cutoffs.competitors._common import (
        extract_initial_state,
        fetch_html,
        rows_from_tables,
    )

    slug = exam_slug(sheet_url) or ""
    rows: list[dict] = []
    for url in cutoff_urls(sheet_url, exam=exam):
        html = fetch_html(url, impersonate=False)
        if not html:
            continue
        # Prefer the lossless INITIAL_STATE article body; fall back to DOM tables.
        state = extract_initial_state(html)
        body = _article_html_from_state(state) if state else None
        source_html = body or html
        page_rows = rows_from_tables(source_html, competitor=COMPETITOR, exam=exam,
                                     slug=slug, page_url=url, page_type="article")
        if page_rows:
            rows += page_rows
            break  # one of the two -cutoff variants is the real page
    return rows
