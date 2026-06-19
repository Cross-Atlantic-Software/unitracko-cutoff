"""Category-2 competitor (aggregator) scrapers.

For exams that carry at least one aggregator link (CollegeDunia / Shiksha /
Careers360 / CollegeDekho — the "column F onwards" set), we download *all* the
cutoff data each site exposes. This is the client's Category 2 ("all exams which
have at least one competitor link"). NOTE: the segmentation is a priority partition,
so an exam that ALSO has a specific official link is classified cat-1, not cat-2;
``run.py`` scrapes the cat-2 bucket by default and can additionally cover the
competitor links of cat-1 exams via ``--category all``. Per the client's brief,
the schema is **specific to each competitor** and each writes its OWN raw table —
these are never merged into the unified official schema.

Design:
- Each competitor module exposes ``COMPETITOR`` (name) and ``cutoff_urls(sheet_url)``
  — a pure-stdlib builder that turns the sheet's landing/search URL into the
  concrete cutoff-page URL(s) for that site (or ``[]`` when the link is a generic
  search with no resolvable slug). It also exposes ``scrape(sheet_url, exam)``
  which fetches + parses into a list of raw dict rows (heavy deps imported lazily).
- :mod:`cutoffs.competitors._common` holds the shared toolkit (browser-UA fetch,
  HTML-table + JSON-blob extraction, heading→table attribution, rank coercion).
- :mod:`cutoffs.competitors.run` orchestrates: read ``data/segmentation.csv``,
  run each site over its exams, write ``data/competitor_<name>.parquet`` + sidecar.

The raw schema below is a *superset* (union of all four sites' fields) so every
heterogeneous table survives losslessly; ``raw_cells`` keeps the full original row
as JSON for anything the column detection misses.
"""
from __future__ import annotations

# Union superset of all four competitors' fields. A rank-based exam fills
# opening/closing_rank; a percentile/score exam (MHT-CET/KCET/NEET) fills
# cutoff_percentile / cutoff_score_or_marks instead. ``raw_cells`` is the lossless
# fallback for anything not mapped.
RAW_COLUMNS = [
    "source_competitor",   # "collegedunia" | "shiksha" | "careers360" | "collegedekho"
    "exam",                # exam name from the segmentation sheet
    "exam_slug",           # site slug parsed from the URL
    "page_url",            # the cutoff page the row came from
    "page_type",           # "exam_cutoff" | "college_cutoff" | "article" | ...
    "table_index",         # which table on the page
    "table_caption",       # nearest preceding heading (institute/year/round context)
    "institute_name",
    "branch_or_course",
    "program",
    "category",            # raw category label (General/OBC/SC/ST/EWS/PwD/...)
    "quota",               # AI / Home-State / region
    "gender",
    "counselling_round",
    "year",
    "opening_rank",
    "closing_rank",
    "cutoff_percentile",   # MHT-CET/KCET/NEET percentile cutoffs
    "cutoff_score_or_marks",
    "rank_range_raw",      # when a cell is a "200-500" range, not two columns
    "raw_header_label",
    "raw_cell_value",
    "raw_cells",           # JSON of the full original table row (lossless fallback)
    "pdf_url",             # linked round/year cutoff PDF, if any
    "notes",
]

# Registry of the competitor modules, filled lazily to avoid importing heavy deps
# at package import. Use :func:`get_competitor`.
_MODULE_NAMES = ["collegedunia", "shiksha", "careers360", "collegedekho"]


def get_competitor(name: str):
    """Import and return a competitor module by name (lazy)."""
    if name not in _MODULE_NAMES:
        raise KeyError(f"unknown competitor {name!r}; known: {_MODULE_NAMES}")
    import importlib

    return importlib.import_module(f"cutoffs.competitors.{name}")


def to_frame(rows: list[dict]):
    """Build a RAW_COLUMNS-shaped DataFrame from raw row dicts (lazy pandas)."""
    import pandas as pd

    df = pd.DataFrame(rows, columns=RAW_COLUMNS)
    return df
