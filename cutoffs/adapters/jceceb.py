"""JCECE adapter — Jharkhand Combined Entrance Competitive Examination Board.

JCECEB publishes per-candidate seat-allotment PDFs (Reg / JEE-Main CML Rank /
category / Allotted Institute / Allotted Branch / Seat Allotted Category) rather
than a cutoff table. The cutoff per (institute, branch, category) is *derived* from
it: the min and max CML rank allotted to that seat group are its opening and closing
rank — which is exactly what a closing rank is. Jharkhand is a small state (~15
engineering colleges in state counselling).

``load_cached`` serves a bundled parsed snapshot; ``fetch_latest`` re-parses live.
"""
from __future__ import annotations

import io
import logging
import re
from collections import defaultdict

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._http import fetch
from cutoffs.registry import register
from cutoffs.schema import empty_frame, normalize
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)

_PDF_SPECS = [
    {"url": "https://jceceb.jharkhand.gov.in/IMP_l/658.pdf", "year": 2024,
     "round": "2nd Round"},
]
_DEDUP_COLS = ["Institute", "Branch", "Category", "Year", "Round",
               "OpeningRank", "ClosingRank"]


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\n", " ")).strip()


def _allotment_columns(cells: list[str]) -> dict[str, int] | None:
    """Column indices for a JCECE allotment header row, or None if not a header."""
    low = [c.lower() for c in cells]
    idx: dict[str, int] = {}
    for i, c in enumerate(low):
        if "cml rank" in c:
            idx["rank"] = i
        elif "alloted institute" in c:
            idx["Institute"] = i
        elif "alloted branch" in c:
            idx["Branch"] = i
        elif "seat alloted category" in c:
            idx["Category"] = i
    return idx if "Institute" in idx and "rank" in idx else None


def parse_jceceb_pdf(data: bytes, *, year: int, round_label: str,
                     source_url: str) -> pd.DataFrame:
    """Parse a JCECE allotment PDF and derive (institute, branch, category) cutoffs."""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - optional dependency
        return empty_frame()
    groups: dict[tuple, list[int]] = defaultdict(list)
    idx: dict[str, int] | None = None
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    for row in table or []:
                        cells = [_norm(c) for c in row]
                        head = _allotment_columns(cells)
                        if head is not None:
                            idx = head
                            continue
                        if idx is None or max(idx.values()) >= len(cells):
                            continue
                        institute = cells[idx["Institute"]]
                        rank = cells[idx["rank"]]
                        if not institute or not re.fullmatch(r"\d+", rank):
                            continue
                        branch = cells[idx["Branch"]] if "Branch" in idx else ""
                        category = cells[idx["Category"]] if "Category" in idx else ""
                        groups[(institute, branch, category)].append(int(rank))
    except Exception:  # noqa: BLE001 — a malformed page never sinks the parse
        pass
    if not groups:
        return empty_frame()
    records = [{
        "Body": "JCECE", "Exam": "JCECE", "Level": "UG", "State": "Jharkhand",
        "Institute": inst, "Branch": branch or None, "Category": cat or None,
        "Year": year, "Round": round_label,
        "OpeningRank": min(ranks), "ClosingRank": max(ranks),
        "SourceURL": source_url,
    } for (inst, branch, cat), ranks in groups.items()]
    return normalize(pd.DataFrame(records))


def _dedup(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = [c for c in _DEDUP_COLS if c in df.columns]
    return df.drop_duplicates(subset=cols).reset_index(drop=True)


@register
class JCECE(CutoffSource):
    meta = SourceMeta(
        name="jceceb",
        exam="JCECE",
        level="UG",
        states=("Jharkhand",),
        data_format="pdf",
        body_label="JCECE",
        website="https://jceceb.jharkhand.gov.in/",
        source_url="https://jceceb.jharkhand.gov.in/",
    )

    def load_cached(self) -> pd.DataFrame:
        return _dedup(self.normalize(read_bundled("jceceb_official.csv.gz")))

    def fetch_latest(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for spec in _PDF_SPECS:
            try:
                resp = fetch(spec["url"], timeout=90.0, retries=1)
                df = parse_jceceb_pdf(resp.content, year=spec["year"],
                                      round_label=spec["round"], source_url=spec["url"])
                if not df.empty:
                    frames.append(df)
            except Exception as exc:  # noqa: BLE001 — one bad PDF never blocks the rest
                _log.debug("jceceb fetch_latest skipped %s: %s", spec["url"], exc)
        if not frames:
            return self.load_cached()
        return _dedup(pd.concat(frames, ignore_index=True))
