"""Project the unified cutoff schema down to the client's 14-column deliverable.

The client's Category-1 output is a fixed 14-column table. Our internal unified
schema (:mod:`cutoffs.schema`, 18 columns) is a superset, so the deliverable is a
straight select + rename — ``Institute`` becomes ``College Name``; ``Body``,
``Level``, ``Category`` and ``CategoryGroup`` are dropped. The reservation
``Category`` can be re-added with ``include_category=True`` if the client wants it.

The column map is pure data and ``project_records`` works on plain dict rows, so
the mapping is testable without pandas; ``to_cat1_deliverable`` is the pandas wrapper.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DELIVERABLE_CSV = ROOT / "data" / "cat1_deliverable.csv"

# (unified schema column, client deliverable label), in the client's order.
DELIVERABLE_COLUMNS: list[tuple[str, str]] = [
    ("Exam", "Exam Name"),
    ("Website", "Link of website"),
    ("Institute", "College Name"),
    ("City", "City"),
    ("State", "State"),
    ("Program", "Program"),
    ("Branch", "Branch"),
    ("Year", "Year - cutoff"),
    ("Round", "Round #"),
    ("Gender", "Gender"),
    ("Quota", "Quota"),
    ("OpeningRank", "Opening Rank"),
    ("ClosingRank", "Closing Rank"),
    ("SourceURL", "Link - Data Taken from"),
]

# The reservation category, inserted after Quota when include_category=True.
_CATEGORY_COLUMN = ("Category", "Category")


def deliverable_columns(include_category: bool = False) -> list[tuple[str, str]]:
    if not include_category:
        return list(DELIVERABLE_COLUMNS)
    cols = list(DELIVERABLE_COLUMNS)
    idx = next(i for i, (s, _) in enumerate(cols) if s == "Quota") + 1
    cols.insert(idx, _CATEGORY_COLUMN)
    return cols


def deliverable_rename(include_category: bool = False) -> dict[str, str]:
    return {schema: label for schema, label in deliverable_columns(include_category)}


def project_records(records: list[dict], include_category: bool = False) -> list[dict]:
    """Project plain dict rows (unified-schema keys) to client-labelled dict rows.

    Missing source keys become None. Pure stdlib — used for the non-pandas path and
    the tests.
    """
    cols = deliverable_columns(include_category)
    out = []
    for r in records:
        out.append({label: r.get(schema) for schema, label in cols})
    return out


def to_cat1_deliverable(df, include_category: bool = False):
    """Select + rename a unified-schema DataFrame to the 14-column deliverable."""
    cols = deliverable_columns(include_category)
    schema_cols = [s for s, _ in cols]
    projected = df.reindex(columns=schema_cols)
    return projected.rename(columns=dict(cols))


def write_deliverable(df, *, out_csv: Path = DELIVERABLE_CSV, out_parquet: Path | None = None,
                      include_category: bool = False):
    """Write the deliverable CSV (and optionally parquet). Returns the projected frame."""
    projected = to_cat1_deliverable(df, include_category=include_category)
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    projected.to_csv(out_csv, index=False)
    if out_parquet is not None:
        projected.to_parquet(Path(out_parquet), index=False)
    return projected
