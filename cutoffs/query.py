"""DuckDB query layer over the Parquet dataset.

All filtering and aggregation is DuckDB SQL run directly against the Parquet
file — no intermediate load into pandas until the result comes back. The
``CutoffQuery`` builder keeps the Streamlit UI free of raw SQL.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from cutoffs.schema import COLUMNS, empty_frame
from cutoffs.storage import DEFAULT_PATH

# Columns the UI offers as equality filters (everything categorical).
FILTERABLE = [
    "Body", "Exam", "Level", "State", "Year",
    "Round", "Institute", "Branch", "Category", "Quota", "Gender",
]


class CutoffQuery:
    """A small, chainable filter builder that compiles to one DuckDB query."""

    def __init__(self, path: str | Path = DEFAULT_PATH):
        self._path = Path(path)
        self._where: list[str] = []
        self._params: list[object] = []
        self._limit: int | None = None

    # -- filter construction -------------------------------------------------

    def where(self, column: str, value: object) -> "CutoffQuery":
        """Add an equality filter (ignored when value is None/empty)."""
        if column not in COLUMNS:
            raise KeyError(f"unknown column: {column!r}")
        if value is None or value == "":
            return self
        self._where.append(f'"{column}" = ?')
        self._params.append(value)
        return self

    def where_in(self, column: str, values: list[object]) -> "CutoffQuery":
        """Add an IN filter (ignored when the list is empty)."""
        if column not in COLUMNS:
            raise KeyError(f"unknown column: {column!r}")
        values = [v for v in (values or []) if v is not None and v != ""]
        if not values:
            return self
        placeholders = ", ".join("?" for _ in values)
        self._where.append(f'"{column}" IN ({placeholders})')
        self._params.extend(values)
        return self

    def max_closing_rank(self, rank: int | None) -> "CutoffQuery":
        """Keep only rows a candidate with this rank could plausibly get."""
        if rank is None:
            return self
        self._where.append('"ClosingRank" >= ?')
        self._params.append(int(rank))
        return self

    def limit(self, n: int | None) -> "CutoffQuery":
        # Clamp to a non-negative value; a negative LIMIT would raise a raw
        # DuckDB BinderException. Falsy (0/None) means "no limit".
        self._limit = max(int(n), 0) if n else None
        return self

    # -- execution -----------------------------------------------------------

    def _sql(self) -> str:
        src = f"read_parquet('{self._path.as_posix()}')"
        sql = f"SELECT {', '.join(self._col_list())} FROM {src}"
        if self._where:
            sql += " WHERE " + " AND ".join(self._where)
        sql += ' ORDER BY "ClosingRank" NULLS LAST'
        if self._limit is not None:
            sql += f" LIMIT {self._limit}"
        return sql

    @staticmethod
    def _col_list() -> list[str]:
        return [f'"{c}"' for c in COLUMNS]

    def to_df(self) -> pd.DataFrame:
        """Execute and return results as a schema-ordered DataFrame."""
        if not self._path.exists():
            return empty_frame()
        with duckdb.connect() as con:
            df = con.execute(self._sql(), self._params).fetch_df()
        return df[COLUMNS] if len(df) else empty_frame()


def distinct_values(column: str, path: str | Path = DEFAULT_PATH) -> list:
    """Return the sorted distinct non-null values of a column (for UI menus)."""
    if column not in COLUMNS:
        raise KeyError(f"unknown column: {column!r}")
    path = Path(path)
    if not path.exists():
        return []
    src = f"read_parquet('{path.as_posix()}')"
    sql = f'SELECT DISTINCT "{column}" AS v FROM {src} WHERE "{column}" IS NOT NULL ORDER BY v'
    with duckdb.connect() as con:
        rows = con.execute(sql).fetchall()
    return [r[0] for r in rows]
