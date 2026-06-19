"""The unified cutoff schema and tolerant normalization.

Every adapter emits EXACTLY the columns in ``COLUMNS``, in this order. The
normalizer is deliberately forgiving: it never crashes on a missing column or a
bad row, it just coerces what it can and leaves the rest null.
"""

from __future__ import annotations

import re

import pandas as pd

# The 18 canonical columns, in canonical order. This list is the contract.
COLUMNS: list[str] = [
    "Body",        # counseling body, e.g. "JoSAA", "MHT-CET"
    "Exam",        # qualifying exam, e.g. "JEE Advanced", "MHT-CET"
    "Website",     # official homepage of the exam/body (link)
    "Level",       # "UG" or "PG"
    "State",       # state scope, or "All India"
    "City",        # city of the institute (best-effort, parsed from name)
    "Institute",   # college / institute name
    "Program",     # degree programme, e.g. "B.E./B.Tech", "B.Arch", "Diploma"
    "Branch",      # academic branch / specialization
    "Category",    # reservation category as published, e.g. "OPEN", "EZ", "SM"
    "CategoryGroup",  # normalized super-category, e.g. "General", "OBC", "SC"
    "Quota",       # quota, e.g. "AI" (All India), "HS" (Home State)
    "Gender",      # "Gender-Neutral", "Female-only", ...
    "Year",        # admission year (int)
    "Round",       # counseling round, kept as text ("1", "Mock 1", ...)
    "OpeningRank",  # nullable integer
    "ClosingRank",  # nullable integer
    "SourceURL",   # link the data was taken from (PDF/portal)
]

# Pandas dtypes per column. Nullable types throughout so a bad/missing value
# becomes <NA> instead of raising.
_TEXT = "string"
_INT = "Int64"  # pandas nullable integer

DTYPES: dict[str, str] = {
    "Body": _TEXT,
    "Exam": _TEXT,
    "Website": _TEXT,
    "Level": _TEXT,
    "State": _TEXT,
    "City": _TEXT,
    "Institute": _TEXT,
    "Program": _TEXT,
    "Branch": _TEXT,
    "Category": _TEXT,
    "CategoryGroup": _TEXT,
    "Quota": _TEXT,
    "Gender": _TEXT,
    "Year": _INT,
    "Round": _TEXT,
    "OpeningRank": _INT,
    "ClosingRank": _INT,
    "SourceURL": _TEXT,
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


def _dedouble(text: str) -> str:
    """Collapse PDF glyph-doubling ('OOBBCC' -> 'OBC', 'CCoolllleeggee' -> 'College').

    Some source PDFs (e.g. Rajasthan DTE) emit every character twice. Two cases:

    - Strict: an even-length token whose every adjacent pair is identical
      (``c0c0c1c1…``) is unambiguously doubled — collapse it. Catches short codes
      ("SSCC", "OOBBCC", "MMaallee") that the loose check below misses. Ordinary
      words almost never pair this way ("BOOK" -> (B,O)(O,K) fails).
    - Loose: a longer string that is *mostly* doubled but carries the odd stray
      character (a lone newline, single spaces between doubled words) is collapsed
      greedily, tolerating those singles.

    Text without the signature ("College", "Bhilwara") is returned untouched.
    """
    n = len(text)
    if n >= 4 and n % 2 == 0 and all(text[i] == text[i + 1] for i in range(0, n, 2)):
        return text[::2]
    if n < 8:
        return text
    doubled = sum(text[i] == text[i + 1] for i in range(n - 1))
    if doubled < (n - 1) * 0.4:
        return text
    out: list[str] = []
    i = 0
    while i < n:
        out.append(text[i])
        i += 2 if i + 1 < n and text[i] == text[i + 1] else 1
    return "".join(out)


def _clean_text(value: str) -> str:
    """De-double glyph-doubled text and collapse internal whitespace/line-breaks."""
    return re.sub(r"\s+", " ", _dedouble(value)).strip()


def _looks_doubled(text: str) -> bool:
    """True if ``text`` carries the glyph-doubling signature (see :func:`_dedouble`)."""
    n = len(text)
    if n >= 4 and n % 2 == 0 and all(text[i] == text[i + 1] for i in range(0, n, 2)):
        return True
    if n < 8:
        return False
    return sum(text[i] == text[i + 1] for i in range(n - 1)) >= (n - 1) * 0.4


def dedouble_rows(df: pd.DataFrame, check_cols: tuple[str, ...]) -> pd.DataFrame:
    """De-double EVERY cell of rows whose ``check_cols`` show the doubled signature.

    Some sources (Rajasthan DTE) glyph-double whole rows — including the rank
    *digits* ("5584" -> "55558844"). Text columns are repaired by ``normalize``,
    but the integer rank columns are coerced straight to int and would keep the
    inflated value. Detecting the doubled rows by their text fields and cleaning
    the entire row (string cells) BEFORE coercion repairs the ranks too, while
    leaving the file's clean rows untouched (so a real rank like 1122 is safe).
    """
    if df is None or df.empty:
        return df
    cols = [c for c in check_cols if c in df.columns]
    if not cols:
        return df
    mask = df.apply(
        lambda row: any(isinstance(row[c], str) and _looks_doubled(row[c].strip())
                        for c in cols),
        axis=1,
    )
    if not mask.any():
        return df
    out = df.copy()
    for c in out.columns:
        out.loc[mask, c] = out.loc[mask, c].map(
            lambda v: pd.NA if pd.isna(v) else _clean_text(str(v)))
    return out


def _coerce_text(series: pd.Series) -> pd.Series:
    """Coerce a column to nullable, *cleaned* string.

    Cleaning (de-glyph-doubling + whitespace collapse) happens HERE so that any
    frame passed through :func:`normalize` is genuinely clean — callers never have
    to remember a second pass. Bad/blank values become <NA>.
    """
    s = series.astype("string")
    cleaned = s.map(lambda v: pd.NA if v is None or pd.isna(v) else _clean_text(str(v)))
    out = cleaned.astype("string")
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
