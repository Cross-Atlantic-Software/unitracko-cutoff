"""UPTAC adapter — UP Technical Admission & Counselling (AKTU), Uttar Pradesh.

UPTAC publishes its opening/closing ranks as on-portal HTML reports (one per
programme group: B.Tech., UG, PG/MBA-MCA, NATA), each a clean table with
Institute / Program / Stream / Quota / Category / Seat Gender / Opening / Closing
Rank. Unlike the WBJEE form, these render server-side, so they parse with
pandas.read_html. ``fetch_latest`` discovers the current report links from the
or-cr page (the ``enc`` tokens rotate per year) and parses each; ``load_cached``
serves a bundled parsed snapshot.
"""
from __future__ import annotations

import io
import logging
import re

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.registry import register
from cutoffs.schema import empty_frame, normalize
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)

_OR_CR_PAGE = "https://uptac.admissions.nic.in/or-cr/"
_REPORT_RE = re.compile(r'href="([^"]*orcrreport[^"]*)"', re.I)
_DEDUP_COLS = ["Institute", "Branch", "Program", "Category", "Quota", "Gender",
               "Year", "Round", "OpeningRank", "ClosingRank"]
# Report "Seat Gender" -> unified Gender.
_GENDER = {"both male and female seats": "Gender-Neutral",
           "female seats": "Female", "male seats": "Male"}


def _report_urls(page_html: str) -> list[str]:
    """The distinct orcrreport links on the or-cr page (enc tokens rotate yearly)."""
    urls = [u.replace("&amp;", "&") for u in _REPORT_RE.findall(page_html or "")]
    return list(dict.fromkeys(urls))


def parse_uptac_report(html: str, *, year: int, source_url: str) -> pd.DataFrame:
    """Parse one UPTAC OR-CR HTML report into unified-schema rows."""
    try:
        tables = pd.read_html(io.StringIO(html))
    except (ValueError, ImportError):
        return empty_frame()
    if not tables:
        return empty_frame()
    t = max(tables, key=len)
    cols = {c.lower(): c for c in t.columns}
    inst = cols.get("institute")
    if inst is None or "closing rank" not in cols:
        return empty_frame()
    out = pd.DataFrame({
        "Body": "UPTAC", "Exam": "UPTAC", "Level": "UG", "State": "Uttar Pradesh",
        "Institute": t[inst],
        "Program": t.get(cols.get("program", ""), ""),
        "Branch": t.get(cols.get("stream", ""), ""),
        "Quota": t.get(cols.get("quota", ""), ""),
        "Category": t.get(cols.get("category", ""), ""),
        "Gender": t.get(cols.get("seat gender", ""), "").map(
            lambda v: _GENDER.get(str(v).strip().lower(), v)),
        "Year": year, "Round": t.get(cols.get("round", ""), ""),
        "OpeningRank": t.get(cols.get("opening rank", "")),
        "ClosingRank": t.get(cols.get("closing rank", "")),
        "SourceURL": source_url,
    })
    return normalize(out)


def _dedup(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = [c for c in _DEDUP_COLS if c in df.columns]
    return df.drop_duplicates(subset=cols).reset_index(drop=True)


@register
class UPTAC(CutoffSource):
    meta = SourceMeta(
        name="uptac",
        exam="UPTAC",
        level="UG",
        states=("Uttar Pradesh",),
        data_format="html",
        body_label="UPTAC",
        website="https://uptac.admissions.nic.in/",
        source_url="https://uptac.admissions.nic.in/or-cr/",
    )

    def load_cached(self) -> pd.DataFrame:
        return _dedup(self.normalize(read_bundled("uptac_official.csv.gz")))

    def fetch_latest(self) -> pd.DataFrame:
        """Discover the live report links and parse each; fall back to cached."""
        from cutoffs.competitors._common import fetch_html

        page = fetch_html(_OR_CR_PAGE, impersonate=True)
        frames: list[pd.DataFrame] = []
        for url in _report_urls(page):
            try:
                html = fetch_html(url, impersonate=True)
                if not html:
                    continue
                df = parse_uptac_report(html, year=2025, source_url=url)
                if not df.empty:
                    frames.append(df)
            except Exception as exc:  # noqa: BLE001 — one bad report never blocks the rest
                _log.debug("uptac fetch_latest skipped %s: %s", url, exc)
        if not frames:
            return self.load_cached()
        return _dedup(pd.concat(frames, ignore_index=True))
