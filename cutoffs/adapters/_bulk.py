"""Category-1 bulk official-link scraper.

A single registered source that walks every Category-1 exam (those with a
*specific official cutoff link*, per :mod:`cutoffs.segmentation`), looks up each
link's probe bucket, and dispatches to the right reusable fetcher
(:mod:`cutoffs.dispatch`). It is breadth insurance, not the primary data source:
per the project's reality check only ~18 of the Category-1 official links expose
static rank tables, so most rows here come back empty; the dead/blocked links are
recorded in ``last_stats`` for the run report (they are not auto-retried — the
separate "no link at all" exams are what Category-3 / ``cat3_provenance.run_cat3``
handles). The curated per-body adapters
(josaa/mhtcet/kcet/wbjee/statepdf) remain the real depth.

``fetch_latest()`` returns a normalized frame with per-row ``SourceURL`` (the
official cutoff link) and ``Website`` (the official homepage) set from the
segmentation sheet; it falls back to the bundled snapshot if a live run yields
nothing. Per-URL instrumentation is kept on ``self.last_stats`` for reporting.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from cutoffs.dispatch import dispatch_fetch, load_probe_buckets, strategy_for
from cutoffs.registry import register
from cutoffs.schema import empty_frame, normalize
from cutoffs.segmentation import segment
from cutoffs.source import CutoffSource, SourceMeta

_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "bulk_official_cached.parquet"

# Stop hammering a host after this many consecutive hard failures on it.
_HOST_ERROR_LIMIT = 3


@dataclass
class FetchStat:
    """One per-URL outcome, for the run report."""

    exam: str
    url: str
    bucket: str
    fetcher: str
    rows: int
    status: str   # "ok" | "empty" | "skip" | "dead" | "circuit-open" | "error"
    note: str = ""


@register
class BulkOfficialSource(CutoffSource):
    """Scrape all Category-1 official cutoff links via bucket-dispatched fetchers."""

    meta = SourceMeta(
        name="bulk_official",
        exam="(various — Category-1 official links)",
        level="UG",
        data_format="mixed",
        body_label="",
    )

    def __init__(self, *, jee_remap: bool = False) -> None:
        self.jee_remap = jee_remap
        self.last_stats: list[FetchStat] = []

    # -- fast path -----------------------------------------------------------
    def load_cached(self) -> pd.DataFrame:
        """Return the bundled snapshot of a previous live run (empty if none)."""
        if _CACHE_PATH.exists():
            try:
                return normalize(pd.read_parquet(_CACHE_PATH))
            except Exception:  # noqa: BLE001 — corrupt/old file -> empty, never crash
                return self.empty()
        return self.empty()

    # -- refresh path --------------------------------------------------------
    def _cat1_rows(self):
        return [r for r in segment(jee_remap=self.jee_remap) if r.category == "cat1"]

    def fetch_latest(self) -> pd.DataFrame:
        """Walk every Category-1 link, dispatch per bucket, aggregate the rows."""
        buckets = load_probe_buckets()
        frames: list[pd.DataFrame] = []
        stats: list[FetchStat] = []
        host_errors: dict[str, int] = {}

        for r in self._cat1_rows():
            url = (r.official_cutoff_url or "").strip()
            bucket = buckets.get(url, "")
            strat = strategy_for(bucket)
            host = urlparse(url).netloc.lower()

            if not url or r.prose_cutoff_url:
                stats.append(FetchStat(r.exam, url, bucket, strat.fetcher, 0,
                                       "skip", "no real URL"))
                continue
            if strat.is_dead:
                stats.append(FetchStat(r.exam, url, bucket, strat.fetcher, 0,
                                       "dead", "dead/blocked link -> cat3"))
                continue
            if host_errors.get(host, 0) >= _HOST_ERROR_LIMIT:
                stats.append(FetchStat(r.exam, url, bucket, strat.fetcher, 0,
                                       "circuit-open", f"{host} skipped"))
                continue

            try:
                df = normalize(dispatch_fetch(
                    bucket, url, exam=r.exam, body=self._body_for(r),
                    level="UG", state=""))
            except Exception as exc:  # noqa: BLE001 — defensive; dispatch already guards
                host_errors[host] = host_errors.get(host, 0) + 1
                stats.append(FetchStat(r.exam, url, bucket, strat.fetcher, 0,
                                       "error", str(exc)[:120]))
                continue

            n = len(df)
            if n:
                host_errors[host] = 0
                frames.append(self._attach_links(df, website=r.homepage, source_url=url))
                stats.append(FetchStat(r.exam, url, bucket, strat.fetcher, n, "ok"))
            else:
                stats.append(FetchStat(r.exam, url, bucket, strat.fetcher, 0, "empty"))

        self.last_stats = stats
        combined = pd.concat(frames, ignore_index=True) if frames else empty_frame()
        if combined.empty:
            # Live run yielded nothing (expected for most official links); keep the
            # frontend non-empty by serving the bundled snapshot if we have one.
            return self.load_cached()
        return normalize(combined)

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _body_for(seg_row) -> str:
        """Best-effort Body label — empty here; curated adapters own real bodies."""
        return ""

    @staticmethod
    def _attach_links(df: pd.DataFrame, *, website: str, source_url: str) -> pd.DataFrame:
        """Fill per-row Website/SourceURL from the segmentation sheet (blanks only)."""
        out = df.copy()
        for col, val in (("Website", website), ("SourceURL", source_url)):
            if not val:
                continue
            s = out[col].astype("string")
            out[col] = s.mask(s.isna() | (s.str.strip() == ""), val)
        return out

    def report(self) -> pd.DataFrame:
        """The per-URL instrumentation of the last ``fetch_latest`` as a frame."""
        return pd.DataFrame([s.__dict__ for s in self.last_stats])
