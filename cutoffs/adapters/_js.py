"""JS-rendered source framework (Playwright) — skeleton + worked pattern.

A minority of sources (≈10 in the probe) render their cutoff tables client-side,
so httpx sees an empty shell. For those, render the page in a headless browser,
then hand the resulting HTML to the same generic table extractor used everywhere
else. Playwright is an optional, heavier dependency (``pip install playwright &&
playwright install chromium``); this module imports it lazily so the rest of the
project runs without it.

To add a JS source: subclass ``JSRenderedSource`` and set ``url``/``meta`` (see
the docstring example), or call ``render_html(url)`` directly.
"""
from __future__ import annotations

import pandas as pd

from cutoffs.scrape import extract_tables, is_cutoff_table, map_table, _flatten_columns
from cutoffs.schema import empty_frame, normalize
from cutoffs.source import CutoffSource, SourceMeta

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def render_html(url: str, *, wait_selector: str = "table",
                timeout_ms: int = 20000) -> str:
    """Return fully-rendered HTML for ``url`` (empty string if unavailable)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover - optional dependency
        return ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=_UA)
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            try:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            except Exception:  # noqa: BLE001 - selector optional
                pass
            html = page.content()
            browser.close()
            return html
    except Exception:  # noqa: BLE001
        return ""


def scrape_js_cutoffs(url: str, *, exam: str, body: str = "", year: int | None = None,
                      level: str | None = None, state: str | None = None) -> pd.DataFrame:
    """Render with Playwright, then reuse the standard table->schema pipeline."""
    html = render_html(url)
    if not html:
        return empty_frame()
    frames = []
    for tbl in extract_tables(html):
        if is_cutoff_table(_flatten_columns(tbl)):
            mapped = map_table(tbl, exam=exam, body=body, year=year,
                               level=level, state=state)
            if not mapped.empty:
                frames.append(mapped)
    if not frames:
        return empty_frame()
    return normalize(pd.concat(frames, ignore_index=True))


class JSRenderedSource(CutoffSource):
    """Skeleton for a JS-rendered body.

    Example::

        class MySpaSource(JSRenderedSource):
            meta = SourceMeta(name="myspa", exam="MY-SPA", level="UG")
            url = "https://example.edu/cutoffs"
    """

    meta = SourceMeta(name="js", exam="JS", level="UG", data_format="js")
    url: str = ""

    def load_cached(self) -> pd.DataFrame:
        return self.empty()

    def fetch_latest(self) -> pd.DataFrame:
        if not self.url:
            return self.empty()
        return self.normalize(
            scrape_js_cutoffs(self.url, exam=self.meta.exam, body=self.meta.exam)
        )
