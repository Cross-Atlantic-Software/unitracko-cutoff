"""Shared parser for Telangana/Andhra-style "last rank" cutoff PDFs.

TGEAPCET (TS EAMCET) and APEAPCET (AP EAMCET) publish a flat institute-wise table:
one row per (institute, branch) with category x gender columns — OC_BOYS, OC_GIRLS,
BC_A_BOYS, ... SC_I_BOYS, ST_GIRLS, EWS_BOYS — each cell the last (closing) rank.

``parse_lastrank_pdf`` reads every table, detects the institute/branch/place columns
and the category x gender rank columns by header, and melts the ranks into unified
schema rows. Tolerant: a malformed page never raises. The header repeats on every
page of these PDFs, so per-table detection captures all rows.
"""
from __future__ import annotations

import io
import re

import pandas as pd

from cutoffs.schema import empty_frame, normalize

_DEDUP_COLS = ["Institute", "Branch", "Category", "Gender", "Year", "ClosingRank"]


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _rank_header(header: str) -> tuple[str, str] | None:
    """Return (category, gender) for a ``<CAT>_<BOYS|GIRLS>`` rank column, else None.

    Strips every non-letter (these PDFs wrap headers mid-word, e.g. ``OC_BO\\nYS``),
    so ``OC_BOYS`` -> ("OC", "Male"), ``BC_A_GIRLS`` -> ("BCA", "Female").
    """
    token = re.sub(r"[^A-Z]", "", _norm(header).upper())
    m = re.search(r"(BOYS|GIRLS)$", token)
    if not m:
        return None
    category = token[: m.start()]
    if not category:
        return None
    return category, ("Male" if m.group(1) == "BOYS" else "Female")


def _find(cols: list[str], pattern: str) -> int | None:
    for i, c in enumerate(cols):
        if re.search(pattern, c, re.I):
            return i
    return None


def parse_lastrank_pdf(data: bytes, *, exam: str, body: str, state: str,
                       year: int, round_label: str, source_url: str) -> pd.DataFrame:
    """Parse a TS/AP last-rank PDF into a normalized unified-schema DataFrame."""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - optional dependency
        return empty_frame()
    records: list[dict] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    if not table or len(table) < 2:
                        continue
                    cols = [_norm(c) for c in table[0]]
                    inst_i = _find(cols, r"institute name|inst.?name|inst_name")
                    if inst_i is None:
                        continue
                    branch_i = (_find(cols, r"branch name")
                                or _find(cols, r"branch.?code|branch_?code"))
                    place_i = _find(cols, r"^place$")
                    rank_cols = {i: rh for i, c in enumerate(cols)
                                 if (rh := _rank_header(c))}
                    if not rank_cols:
                        continue
                    need = max([*rank_cols, inst_i, branch_i or 0, place_i or 0])
                    for row in table[1:]:
                        if len(row) <= need:
                            continue
                        institute = _norm(row[inst_i])
                        if not institute:
                            continue
                        branch = _norm(row[branch_i]) if branch_i is not None else ""
                        city = _norm(row[place_i]) if place_i is not None else None
                        for ci, (cat, gender) in rank_cols.items():
                            v = _norm(row[ci])
                            if not re.fullmatch(r"\d+", v):
                                continue
                            records.append({
                                "Body": body, "Exam": exam, "Level": "UG",
                                "State": state, "City": city, "Institute": institute,
                                "Branch": branch, "Category": cat, "Gender": gender,
                                "Year": year, "Round": round_label,
                                "ClosingRank": int(v), "SourceURL": source_url,
                            })
    except Exception:  # noqa: BLE001 — a malformed page never sinks the parse
        return normalize(pd.DataFrame(records)) if records else empty_frame()
    if not records:
        return empty_frame()
    return normalize(pd.DataFrame(records))


def dedup_lastrank(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate rows (same institute/branch/category/gender/year/rank)."""
    if df.empty:
        return df
    cols = [c for c in _DEDUP_COLS if c in df.columns]
    return df.drop_duplicates(subset=cols).reset_index(drop=True)
