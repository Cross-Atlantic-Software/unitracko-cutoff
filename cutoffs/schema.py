"""The unified cutoff schema and tolerant normalization.

Every adapter emits EXACTLY the columns in ``COLUMNS``, in this order. The
normalizer is deliberately forgiving: it never crashes on a missing column or a
bad row, it just coerces what it can and leaves the rest null.
"""

from __future__ import annotations

import pandas as pd

# The 13 canonical columns, in canonical order. This list is the contract.
COLUMNS: list[str] = [
    "Body",        # counseling body, e.g. "JoSAA", "MHT-CET"
    "Exam",        # qualifying exam, e.g. "JEE Advanced", "MHT-CET"
    "Level",       # "UG" or "PG"
    "State",       # state scope, or "All India"
    "Year",        # admission year (int)
    "Round",       # counseling round, kept as text ("1", "Mock 1", ...)
    "Institute",   # college / institute name
    "Branch",      # academic program / branch
    "Category",    # reservation category, e.g. "OPEN", "OBC-NCL", "SC"
    "Quota",       # quota, e.g. "AI" (All India), "HS" (Home State)
    "Gender",      # "Gender-Neutral", "Female-only", ...
    "OpeningRank",  # nullable integer
    "ClosingRank",  # nullable integer
]

# Pandas dtypes per column. Nullable types throughout so a bad/missing value
# becomes <NA> instead of raising.
_TEXT = "string"
_INT = "Int64"  # pandas nullable integer

DTYPES: dict[str, str] = {
    "Body": _TEXT,
    "Exam": _TEXT,
    "Level": _TEXT,
    "State": _TEXT,
    "Year": _INT,
    "Round": _TEXT,
    "Institute": _TEXT,
    "Branch": _TEXT,
    "Category": _TEXT,
    "Quota": _TEXT,
    "Gender": _TEXT,
    "OpeningRank": _INT,
    "ClosingRank": _INT,
}

_INT_COLUMNS = [c for c, t in DTYPES.items() if t == _INT]
_TEXT_COLUMNS = [c for c, t in DTYPES.items() if t == _TEXT]


def empty_frame() -> pd.DataFrame:
    """Return an empty DataFrame with the canonical columns and dtypes."""
    df = pd.DataFrame({c: pd.Series(dtype=DTYPES[c]) for c in COLUMNS})
    return df[COLUMNS]


def _coerce_int(series: pd.Series) -> pd.Series:
    """Coerce a column to nullable Int64, tolerating commas, blanks, floats."""
    if series.dtype == _INT:
        return series
    # For any non-numeric dtype (object, "string", or pandas 3.0's "str"),
    # strip thousands separators and stray whitespace before parsing.
    cleaned = series
    if not pd.api.types.is_numeric_dtype(series):
        cleaned = series.astype("string").str.replace(",", "", regex=False).str.strip()
        cleaned = cleaned.replace({"": pd.NA, "-": pd.NA, "NA": pd.NA, "nan": pd.NA})
    numeric = pd.to_numeric(cleaned, errors="coerce")
    return numeric.round().astype(_INT)


def _coerce_text(series: pd.Series) -> pd.Series:
    """Coerce a column to nullable string, trimming whitespace."""
    out = series.astype("string").str.strip()
    return out.replace({"": pd.NA})


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` conformed to the unified schema.

    - Adds any missing canonical columns as all-null.
    - Drops any columns not in the schema.
    - Reorders to canonical order.
    - Coerces dtypes tolerantly (bad values become <NA>, never an exception).
    """
    if df is None or len(df.columns) == 0:
        return empty_frame()

    # Tolerate duplicate column labels: a repeated header would make ``df[col]``
    # return a DataFrame (not a Series) and break coercion. Keep the first.
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]

    out = pd.DataFrame(index=df.index)
    for col in COLUMNS:
        if col in df.columns:
            series = df[col]
            if col in _INT_COLUMNS:
                out[col] = _coerce_int(series)
            else:
                out[col] = _coerce_text(series)
        else:
            out[col] = pd.Series(pd.NA, index=df.index, dtype=DTYPES[col])

    return out[COLUMNS].reset_index(drop=True)
