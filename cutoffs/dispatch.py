"""Format dispatch for the Category-1 official-link scraper.

Each official cutoff URL was deep-probed (``data/source_probe.csv``) into a
*bucket* describing what lives there: a rank table, a no-rank HTML page, a
JS-only SPA, a PDF, or a dead link. This module turns a bucket into a fetch
*strategy* (which existing fetcher to use + timeout/retries) and dispatches the
actual fetch to the right reusable adapter:

    html_*      -> cutoffs.scrape.scrape_cutoffs        (httpx + table heuristics)
    js_only     -> cutoffs.adapters._js.scrape_js_cutoffs (Playwright render)
    pdf         -> _http.fetch + cutoffs.adapters._pdf.parse_cutoff_pdf
    http_*/error/no_url/non_html -> nothing (dead/blocked; the bulk source records
                                   these in its run report — they are not auto-retried)

The *decision* layer (``strategy_for`` / ``fetcher_name`` / ``load_probe_buckets``)
is deliberately pure standard library so it is unit-testable without pandas or a
network; the pandas/httpx fetchers are imported lazily inside ``dispatch_fetch``.
"""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE_PATH = ROOT / "data" / "source_probe.csv"

# Fetcher keys (which reusable adapter handles a bucket).
HTML, JS, PDF, NONE = "html", "js", "pdf", "none"


@dataclass(frozen=True)
class Strategy:
    """How to fetch a given bucket: which fetcher, and its timeout/retries."""

    fetcher: str          # HTML | JS | PDF | NONE
    timeout: float = 30.0
    retries: int = 1

    @property
    def is_dead(self) -> bool:
        return self.fetcher == NONE


# Explicit strategy per observed probe bucket. Anything not listed is resolved by
# the prefix rules in :func:`strategy_for` (html* -> HTML, http_*/error -> NONE).
_STRATEGY: dict[str, Strategy] = {
    # HTML — has (or may have) rank tables; reuse the generic HTML scraper.
    "html_table_rank": Strategy(HTML, timeout=30.0, retries=1),
    "html_rank_notable": Strategy(HTML, timeout=30.0, retries=1),
    "html_other": Strategy(HTML, timeout=30.0, retries=1),
    "html_table_norank": Strategy(HTML, timeout=30.0, retries=1),
    # JS-rendered SPA — needs Playwright; longer wait, no retry (expensive).
    "js_only": Strategy(JS, timeout=25.0, retries=0),
    # PDF — download then pdfplumber-parse; harder retry, longer timeout.
    "pdf": Strategy(PDF, timeout=45.0, retries=2),
    # Dead / unreachable / no official link — never fetched; the bulk source records
    # these as dead in its run report (not auto-retried).
    "http_404": Strategy(NONE), "http_403": Strategy(NONE),
    "http_500": Strategy(NONE), "http_503": Strategy(NONE),
    "error": Strategy(NONE), "no_url": Strategy(NONE),
    "non_html": Strategy(NONE),
}

_DEAD = Strategy(NONE)


def strategy_for(bucket: str | None) -> Strategy:
    """Return the fetch :class:`Strategy` for a probe bucket (tolerant of unknowns)."""
    b = (bucket or "").strip()
    if b in _STRATEGY:
        return _STRATEGY[b]
    if b.startswith("http_") or b == "error":
        return _DEAD
    if b.startswith("html"):
        return Strategy(HTML, timeout=30.0, retries=1)
    if b.startswith("pdf"):
        return Strategy(PDF, timeout=45.0, retries=2)
    return _DEAD  # no_url, non_html, blank, anything else -> dead


def fetcher_name(bucket: str | None) -> str:
    """Convenience: the fetcher key (``html``/``js``/``pdf``/``none``) for a bucket."""
    return strategy_for(bucket).fetcher


def is_dead(bucket: str | None) -> bool:
    """True if the bucket should not be fetched (dead link / no official source)."""
    return strategy_for(bucket).is_dead


# --------------------------------------------------------------------------
def load_probe_buckets(path: Path = PROBE_PATH) -> dict[str, str]:
    """Map each probed URL to its bucket (stdlib only). Empty dict if absent."""
    if not Path(path).exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return {r["url"].strip(): r.get("bucket", "").strip()
                for r in csv.DictReader(fh) if r.get("url")}


def bucket_breakdown(buckets: list[str]) -> dict[str, int]:
    """Tally a list of buckets (for the scrapeability report)."""
    return dict(Counter((b or "").strip() or "(blank)" for b in buckets))


# --------------------------------------------------------------------------
def dispatch_fetch(
    bucket: str | None,
    url: str,
    *,
    exam: str,
    body: str = "",
    level: str = "UG",
    state: str = "",
    year: int | None = None,
):
    """Fetch ``url`` using the fetcher its ``bucket`` selects; return a DataFrame.

    Never raises: any fetch/parse failure (or a dead/blank bucket) yields an empty,
    schema-conformant frame. Imports the heavy fetchers lazily so the decision
    layer above stays pandas-free.
    """
    from cutoffs.schema import empty_frame  # lazy: pulls in pandas

    strat = strategy_for(bucket)
    if strat.is_dead or not (url and url.strip()):
        return empty_frame()

    try:
        if strat.fetcher == HTML:
            from cutoffs.scrape import scrape_cutoffs
            return scrape_cutoffs(url, exam=exam, body=body, year=year,
                                  level=level, state=state)
        if strat.fetcher == JS:
            from cutoffs.adapters._js import scrape_js_cutoffs
            return scrape_js_cutoffs(url, exam=exam, body=body, year=year,
                                     level=level, state=state)
        if strat.fetcher == PDF:
            from cutoffs.adapters._http import fetch
            from cutoffs.adapters._pdf import parse_cutoff_pdf
            resp = fetch(url, timeout=strat.timeout, retries=strat.retries)
            return parse_cutoff_pdf(resp.content, exam=exam, body=body,
                                    year=year, level=level, state=state)
    except Exception:  # noqa: BLE001 — tolerant by design; dead/blocked -> empty
        return empty_frame()
    return empty_frame()
