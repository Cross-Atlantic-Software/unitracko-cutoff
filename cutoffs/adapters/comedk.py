"""COMEDK adapter — Consortium of Medical, Engineering & Dental Colleges of Karnataka.

COMEDK conducts UGET for ~150 Karnataka private engineering colleges (distinct from
KCET's government-quota counselling) and publishes a wide cut-off-rank matrix:
College Code / College Name / Seat Type, then one column per branch (AD-…, AI-…,
CS-…) holding the closing rank. The branch columns are chunked across page groups,
each page carrying its own header, so melting every page's branch columns and
accumulating recovers the full college × branch grid.

``load_cached`` serves a bundled parsed snapshot; ``fetch_latest`` re-parses live.
"""
from __future__ import annotations

import io
import logging
import re

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._http import fetch
from cutoffs.registry import register
from cutoffs.schema import empty_frame, normalize
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)

_PDF_SPECS = [
    {"url": "https://www.comedk.org/uploads/Round1_Cutoff_Ranks_after_Engineering_Allotment_Notified_on_12_07_2024.pdf",
     "year": 2024, "round": "Round 1"},
]
_DEDUP_COLS = ["Institute", "Branch", "Category", "Year", "Round", "ClosingRank"]


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\n", " ")).strip()


def _branch(header: str) -> str:
    """Drop the leading branch code ('AD-Artificial …' -> 'Artificial …')."""
    return re.sub(r"^[A-Z0-9]{1,3}\s*-\s*", "", _norm(header)).strip()


def parse_comedk_pdf(data: bytes, *, year: int, round_label: str,
                     source_url: str) -> pd.DataFrame:
    """Parse the COMEDK cut-off matrix PDF (melt branch columns) into unified rows."""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - optional dependency
        return empty_frame()
    records: list[dict] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    if not table:
                        continue
                    hdr = [_norm(c) for c in table[0]]
                    if not hdr or "College Code" not in hdr[0]:
                        continue
                    branches = {i: _branch(hdr[i]) for i in range(3, len(hdr)) if hdr[i]}
                    for row in table[1:]:
                        if len(row) < 3 or not _norm(row[1]):
                            continue
                        institute, seat = _norm(row[1]), _norm(row[2])
                        for i, branch in branches.items():
                            if i >= len(row):
                                continue
                            v = _norm(row[i])
                            if not re.fullmatch(r"\d+", v):
                                continue
                            records.append({
                                "Body": "COMEDK", "Exam": "COMEDK", "Level": "UG",
                                "State": "Karnataka", "Institute": institute,
                                "Branch": branch or None, "Category": seat or None,
                                "Year": year, "Round": round_label,
                                "ClosingRank": int(v), "SourceURL": source_url,
                            })
    except Exception:  # noqa: BLE001 — a malformed page never sinks the parse
        return normalize(pd.DataFrame(records)) if records else empty_frame()
    if not records:
        return empty_frame()
    return normalize(pd.DataFrame(records))


def _dedup(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = [c for c in _DEDUP_COLS if c in df.columns]
    return df.drop_duplicates(subset=cols).reset_index(drop=True)


@register
class COMEDK(CutoffSource):
    meta = SourceMeta(
        name="comedk",
        exam="COMEDK",
        level="UG",
        states=("Karnataka",),
        data_format="pdf",
        body_label="COMEDK",
        website="https://www.comedk.org/",
        source_url="https://www.comedk.org/",
    )

    def load_cached(self) -> pd.DataFrame:
        return _dedup(self.normalize(read_bundled("comedk_official.csv.gz")))

    def fetch_latest(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for spec in _PDF_SPECS:
            try:
                resp = fetch(spec["url"], timeout=90.0, retries=1)
                df = parse_comedk_pdf(resp.content, year=spec["year"],
                                      round_label=spec["round"], source_url=spec["url"])
                if not df.empty:
                    frames.append(df)
            except Exception as exc:  # noqa: BLE001 — one bad PDF never blocks the rest
                _log.debug("comedk fetch_latest skipped %s: %s", spec["url"], exc)
        if not frames:
            return self.load_cached()
        return _dedup(pd.concat(frames, ignore_index=True))
