"""Aggregator-sourced cutoffs distilled from the competitor tables — SEPARATE.

The competitor scrapers (:mod:`cutoffs.competitors`) dump EVERY table on each
aggregator page into ``data/competitor_<site>.parquet``: real cutoff grids, but
also event calendars, "Will be notified" placeholders and "Top colleges"
marketing. Only ~a third of those rows carry an actual rank/percentile.

This module distills those raw tables into the client's 14-column deliverable so
the long tail of exams (the ~80 with no official adapter but a real aggregator
cutoff) becomes visible — WITHOUT polluting the official unified dataset. Exactly
like :mod:`cutoffs.mp_aggregator`, the output is a clearly-labelled side table
(``data/aggregator_cutoffs.csv``), never merged into ``data/cutoffs.parquet``.
Provenance is inherent: the deliverable's "Link - Data Taken from" column is the
aggregator page URL, so every row says where it came from.

``run_aggregator`` reads the bundled parquets (no network) and is pure-pandas; the
row filter and rank recovery are plain functions so they're testable in isolation.
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
AGG_CUTOFFS_CSV = DATA / "aggregator_cutoffs.csv"
COMPETITOR_GLOB = str(DATA / "competitor_*.parquet")

# raw_cells keys that, when numeric, are a usable rank/closing value.
_CLOSING_KEYS = ("closing", "cut off", "cutoff", "cut-off", "rank", "last rank")
_OPENING_KEYS = ("opening", "first rank", "start rank")
_NOISE = ("will be", "to be", "notified", "tba", "n/a", "na", "--", "yet to",
          "coming soon", "updated soon", "select list")


def _clean(value) -> str:
    """Coerce a possibly-NaN/float cell to a stripped string ('' for missing)."""
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() in ("nan", "none", "<na>") else s


def _numeric(value) -> int | None:
    """Parse an int rank out of a messy cell ('1,234', '1234 (Gen)'); else None."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s or any(n in s for n in _NOISE):
        return None
    m = re.search(r"\d[\d,]*", s)
    if not m:
        return None
    try:
        n = int(m.group(0).replace(",", ""))
    except ValueError:
        return None
    # Ranks/percentiles are positive and not absurdly large (drop stray years etc.
    # are kept — a 4-digit year could be a real rank, so only floor at 1).
    return n if n >= 1 else None


def _rank_from_raw(raw_cells) -> tuple[int | None, int | None]:
    """Recover (opening, closing) from the raw_cells JSON when columns are empty."""
    if not isinstance(raw_cells, str) or not raw_cells.strip():
        return None, None
    try:
        cells = json.loads(raw_cells)
    except (ValueError, TypeError):
        return None, None
    if not isinstance(cells, dict):
        return None, None
    opening = closing = None
    for key, val in cells.items():
        k = str(key).lower()
        # An "opening rank" key also contains "rank" — classify as opening FIRST so
        # it never leaks into the closing column.
        if any(t in k for t in _OPENING_KEYS):
            if opening is None:
                opening = _numeric(val)
        elif closing is None and any(t in k for t in _CLOSING_KEYS):
            closing = _numeric(val)
    return opening, closing


_CATEGORY_KEYS = ("category", "caste", "community", "reservation", "quota")


def _category_from_raw(raw_cells) -> str | None:
    """Pull a reservation category out of raw_cells (law/medical grids stash it there)."""
    if not isinstance(raw_cells, str) or not raw_cells.strip():
        return None
    try:
        cells = json.loads(raw_cells)
    except (ValueError, TypeError):
        return None
    if not isinstance(cells, dict):
        return None
    for key, val in cells.items():
        if any(t in str(key).lower() for t in _CATEGORY_KEYS):
            v = _clean(val)
            # The value must look like a category code, not another number/placeholder.
            if v and not v.isdigit() and v.lower() not in ("select list",):
                return v
    return None


def _year_from(row) -> int | None:
    """Year from the column, else a 4-digit 20xx parsed from the caption/branch."""
    year = _numeric(row.get("year"))
    if year and 2000 <= year <= 2099:
        return year
    for field in ("table_caption", "branch_or_course", "institute_name"):
        m = re.search(r"\b(20\d{2})\b", _clean(row.get(field)))
        if m:
            return int(m.group(1))
    return None


def _row_signal(row) -> dict | None:
    """A competitor row -> unified-schema dict if it has a real cutoff, else None.

    Prefers the structured columns the scraper already parsed; falls back to
    digging a rank out of raw_cells. Rows with no numeric rank/percentile/score are
    dropped as noise (calendars, placeholders, marketing).
    """
    opening = _numeric(row.get("opening_rank"))
    closing = _numeric(row.get("closing_rank"))
    pct = _numeric(row.get("cutoff_percentile"))
    score = _numeric(row.get("cutoff_score_or_marks"))
    if opening is None and closing is None:
        opening, closing = _rank_from_raw(row.get("raw_cells"))
    if opening is None and closing is None and pct is None and score is None:
        return None

    institute = _clean(row.get("institute_name"))
    branch = _clean(row.get("branch_or_course")) or _clean(row.get("program"))
    # Require something to identify the row: a college, or a category+rank grid.
    category = _clean(row.get("category")) or _category_from_raw(row.get("raw_cells"))
    if not institute and not (category and (closing or opening)):
        return None

    year = _year_from(row)
    # A closing-only grid is the common aggregator shape; fall back to percentile or
    # score for the closing column only when there's no actual rank.
    return {
        "Exam": _clean(row.get("exam")),
        "Website": None,
        "Institute": institute,
        "City": None,
        "State": None,
        "Program": _clean(row.get("program")) or None,
        "Branch": branch or None,
        "Category": category,
        "Quota": _clean(row.get("quota")) or None,
        "Gender": _clean(row.get("gender")) or None,
        "Year": year,
        "Round": _clean(row.get("counselling_round")) or None,
        "OpeningRank": opening,
        "ClosingRank": closing if closing is not None else (pct or score),
        "SourceURL": _clean(row.get("page_url")) or None,
    }


def collect(parquet_glob: str = COMPETITOR_GLOB, *, include_category: bool = True) -> list[dict]:
    """Distil every bundled competitor parquet into deliverable-shaped rows.

    ``include_category`` keeps the reservation Category column — on by default here
    because these aggregator tables are mostly category-grids where the category is
    the primary axis (unlike the official cat-1 export, which drops it).
    """
    import pandas as pd

    from cutoffs.deliverable import project_records

    prepared: list[dict] = []
    seen: set[tuple] = set()
    for path in sorted(glob.glob(parquet_glob)):
        df = pd.read_parquet(path)
        for raw in df.to_dict("records"):
            row = _row_signal(raw)
            if not row or not row["Exam"]:
                continue
            key = (row["Exam"], row["Institute"], row["Branch"], row["Category"],
                   row["Year"], row["OpeningRank"], row["ClosingRank"])
            if key in seen:
                continue
            seen.add(key)
            prepared.append(row)
    return project_records(prepared, include_category=include_category)


def run_aggregator(out_csv: Path = AGG_CUTOFFS_CSV,
                   parquet_glob: str = COMPETITOR_GLOB,
                   *, include_category: bool = True) -> dict:
    """Write the SEPARATE aggregator deliverable CSV. Returns a stats dict."""
    import csv

    from cutoffs.deliverable import deliverable_columns

    rows = collect(parquet_glob, include_category=include_category)
    labels = [label for _, label in deliverable_columns(include_category)]
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=labels)
        writer.writeheader()
        writer.writerows(rows)
    exams = len({r["Exam Name"] for r in rows})
    colleges = len({r["College Name"] for r in rows if r["College Name"]})
    return {"rows": len(rows), "exams": exams, "colleges": colleges,
            "path": str(out_csv)}


if __name__ == "__main__":  # pragma: no cover - manual run
    stats = run_aggregator()
    print(f"[aggregator] wrote {stats['rows']} rows across {stats['exams']} exams "
          f"({stats['colleges']} colleges) -> {stats['path']}")
