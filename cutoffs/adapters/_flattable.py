"""Shared parser for flat per-record cutoff PDFs.

Several bodies publish a single flat table — one row per
(institute, branch, category, quota, seat-type) with opening/closing rank columns
(Gujarat ACPC, OJEE, ...). They differ only in their header labels, so one parser
driven by a column-map config covers them all. The header typically appears only on
the first page, so the column mapping detected there is carried across the
headerless continuation pages.
"""
from __future__ import annotations

import io
import re

import pandas as pd

from cutoffs.schema import empty_frame, normalize

# Seat-type / gender wording -> the unified Gender vocabulary used elsewhere.
_GENDER = {
    "gender neutral": "Gender-Neutral", "gender-neutral": "Gender-Neutral",
    "female only": "Female-only", "female-only": "Female-only", "female": "Female",
    "male only": "Male", "male": "Male", "both male and female seats": "Gender-Neutral",
}
_TEXT_FIELDS = ("Institute", "Branch", "Category", "Quota", "Gender")
_RANK_FIELDS = ("OpeningRank", "ClosingRank")
_DEDUP_COLS = ["Institute", "Branch", "Category", "Quota", "Gender", "Year",
               "OpeningRank", "ClosingRank"]


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\n", " ")).strip()


def _rank(value: object) -> int | None:
    m = re.match(r"(\d[\d,]*)", _norm(value).replace(",", ""))
    return int(m.group(1)) if m else None


def _header_indices(cols: list[str], colmap: list[tuple[str, str]]) -> dict[str, int] | None:
    """Map unified field -> column index from a header row, or None if not a header.

    ``colmap`` is ordered (header-substring, field); the first column matching a
    field wins. A row is a header only if it locates Institute AND ClosingRank.
    """
    low = [c.lower() for c in cols]
    idx: dict[str, int] = {}
    for i, c in enumerate(low):
        for sub, field in colmap:
            if sub in c and field not in idx:
                idx[field] = i
    return idx if "Institute" in idx and "ClosingRank" in idx else None


def parse_flat_cutoff(data: bytes, *, colmap: list[tuple[str, str]], body: str,
                      exam: str, state: str, year: int, round_label: str,
                      source_url: str, level: str = "UG") -> pd.DataFrame:
    """Parse a flat per-record cutoff PDF into normalized unified-schema rows."""
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
                    for row in table:
                        # A header row (re)sets the column mapping and is skipped;
                        # this tolerates a title row above the header and headers
                        # repeating mid-document. Data rows lack the header
                        # substrings, so they can't be mistaken for a header.
                        head = _header_indices([_norm(c) for c in row], colmap)
                        if head is not None:
                            idx = head
                            continue
                        if idx is None or len(row) <= idx["ClosingRank"]:
                            continue
                        institute = _norm(row[idx["Institute"]])
                        closing = _rank(row[idx["ClosingRank"]])
                        if not institute or closing is None:
                            continue
                        rec = {"Body": body, "Exam": exam, "Level": level,
                               "State": state, "Institute": institute,
                               "Year": year, "Round": round_label,
                               "ClosingRank": closing, "SourceURL": source_url}
                        for field in _TEXT_FIELDS[1:]:  # Branch/Category/Quota/Gender
                            if field in idx and idx[field] < len(row):
                                val = _norm(row[idx[field]])
                                if field == "Gender":
                                    val = _GENDER.get(val.lower(), val)
                                rec[field] = val or None
                        if "OpeningRank" in idx and idx["OpeningRank"] < len(row):
                            rec["OpeningRank"] = _rank(row[idx["OpeningRank"]])
                        records.append(rec)
    except Exception:  # noqa: BLE001 — a malformed page never sinks the parse
        return normalize(pd.DataFrame(records)) if records else empty_frame()
    if not records:
        return empty_frame()
    return normalize(pd.DataFrame(records))


def dedup_flat(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate rows (same institute/branch/category/quota/gender/year/ranks)."""
    if df.empty:
        return df
    cols = [c for c in _DEDUP_COLS if c in df.columns]
    return df.drop_duplicates(subset=cols).reset_index(drop=True)
