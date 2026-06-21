"""Gujarat ACPC adapter — Admission Committee for Professional Courses, Gujarat.

ACPC publishes a flat branch-wise closing-rank PDF for degree engineering:
Inst_Name / Course_name / Alloted_Cat / Quota / Institute Type / First Rank /
Last Rank — one row per (institute, course, category, quota). The header appears
only on the first page; continuation pages are headerless, so the column mapping
detected on page 1 is carried forward. ``load_cached`` serves a bundled parsed
snapshot; ``fetch_latest`` re-parses the live PDF.
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
    {"url": "https://acpc.gujarat.gov.in/assets/uploads/media-uploader/branch-wise-cut-off1718193325.pdf",
     "year": 2024, "round": "Mock Round"},
]
# header label substring -> unified field
_COLMAP = [
    ("inst_name", "Institute"), ("inst name", "Institute"),
    ("course", "Branch"), ("alloted_cat", "Category"), ("cat", "Category"),
    ("quota", "Quota"), ("first rank", "OpeningRank"), ("last rank", "ClosingRank"),
]
_DEDUP_COLS = ["Institute", "Branch", "Category", "Quota", "Year",
               "OpeningRank", "ClosingRank"]


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\n", " ")).strip()


def _rank(value: str) -> int | None:
    m = re.match(r"(\d[\d,]*)", _norm(value).replace(",", ""))
    return int(m.group(1)) if m else None


def _header_indices(cols: list[str]) -> dict[str, int] | None:
    """Map unified field -> column index from a header row, or None if not a header."""
    low = [c.lower() for c in cols]
    idx: dict[str, int] = {}
    for i, c in enumerate(low):
        for sub, field in _COLMAP:
            if sub in c and field not in idx:
                idx[field] = i
    return idx if "Institute" in idx and "ClosingRank" in idx else None


def parse_gujacpc_pdf(data: bytes, *, year: int, round_label: str,
                      source_url: str) -> pd.DataFrame:
    """Parse the ACPC branch-wise cutoff PDF into normalized unified-schema rows."""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - optional dependency
        return empty_frame()
    records: list[dict] = []
    idx: dict[str, int] | None = None  # carried across headerless continuation pages
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    if not table:
                        continue
                    head = _header_indices([_norm(c) for c in table[0]])
                    if head is not None:
                        idx = head
                        body = table[1:]
                    else:
                        body = table  # continuation: every row is data
                    if idx is None:
                        continue
                    for row in body:
                        if len(row) <= idx["ClosingRank"]:
                            continue
                        institute = _norm(row[idx["Institute"]])
                        closing = _rank(row[idx["ClosingRank"]])
                        if not institute or closing is None:
                            continue
                        records.append({
                            "Body": "Gujarat ACPC", "Exam": "Gujarat ACPC",
                            "Level": "UG", "State": "Gujarat", "Institute": institute,
                            "Branch": _norm(row[idx.get("Branch", -1)]) if "Branch" in idx else "",
                            "Category": _norm(row[idx["Category"]]) if "Category" in idx else None,
                            "Quota": _norm(row[idx["Quota"]]) if "Quota" in idx else None,
                            "Year": year, "Round": round_label,
                            "OpeningRank": _rank(row[idx["OpeningRank"]]) if "OpeningRank" in idx else None,
                            "ClosingRank": closing,
                            "SourceURL": source_url,
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
class GujaratACPC(CutoffSource):
    meta = SourceMeta(
        name="gujacpc",
        exam="Gujarat ACPC",
        level="UG",
        states=("Gujarat",),
        data_format="pdf",
        body_label="Gujarat ACPC",
        website="https://acpc.gujarat.gov.in/",
        source_url="https://acpc.gujarat.gov.in/",
    )

    def load_cached(self) -> pd.DataFrame:
        return _dedup(self.normalize(read_bundled("gujacpc_official.csv.gz")))

    def fetch_latest(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for spec in _PDF_SPECS:
            try:
                resp = fetch(spec["url"], timeout=90.0, retries=1)
                df = parse_gujacpc_pdf(resp.content, year=spec["year"],
                                       round_label=spec["round"], source_url=spec["url"])
                if not df.empty:
                    frames.append(df)
            except Exception as exc:  # noqa: BLE001 — one bad PDF never blocks the rest
                _log.debug("gujacpc fetch_latest skipped %s: %s", spec["url"], exc)
        if not frames:
            return self.load_cached()
        return _dedup(pd.concat(frames, ignore_index=True))
