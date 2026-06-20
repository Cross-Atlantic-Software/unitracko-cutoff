"""DuckDB query layer over the Parquet dataset.

All filtering and aggregation is DuckDB SQL run directly against the Parquet
file — no intermediate load into pandas until the result comes back. The
``CutoffQuery`` builder keeps the Streamlit UI free of raw SQL.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

from cutoffs.schema import COLUMNS, empty_frame
from cutoffs.storage import DEFAULT_PATH

# Columns the UI offers as equality filters (everything categorical).
FILTERABLE = [
    "Body", "Exam", "Level", "State", "City", "Year", "Round", "Institute",
    "Program", "Branch", "Category", "CategoryGroup", "Quota", "Gender",
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

    def where_between(
        self, column: str, low: object = None, high: object = None
    ) -> "CutoffQuery":
        """Add an inclusive numeric range filter (each bound optional)."""
        if column not in COLUMNS:
            raise KeyError(f"unknown column: {column!r}")
        if low is not None and low != "":
            self._where.append(f'"{column}" >= ?')
            self._params.append(low)
        if high is not None and high != "":
            self._where.append(f'"{column}" <= ?')
            self._params.append(high)
        return self

    def where_contains(self, column: str, text: str | None) -> "CutoffQuery":
        """Add a case-insensitive substring filter (ignored when text is empty)."""
        if column not in COLUMNS:
            raise KeyError(f"unknown column: {column!r}")
        if not text:
            return self
        # Escape LIKE wildcards so a literal % or _ in the query matches itself.
        safe = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        self._where.append(f"\"{column}\" ILIKE ? ESCAPE '\\'")
        self._params.append(f"%{safe}%")
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

    def count(self) -> int:
        """Return how many rows match the current filters."""
        if not self._path.exists():
            return 0
        src = f"read_parquet('{self._path.as_posix()}')"
        sql = f"SELECT count(*) FROM {src}"
        if self._where:
            sql += " WHERE " + " AND ".join(self._where)
        with duckdb.connect() as con:
            return int(con.execute(sql, self._params).fetchone()[0])

    def group_stats(self, group_by: list[str]) -> pd.DataFrame:
        """Aggregate the filtered rows by ``group_by``, with rank summary stats.

        Returns one row per group: Seats (row count), distinct Institutes/Branches,
        and min/median/avg/max ClosingRank + best OpeningRank. The GROUP BY runs in
        DuckDB over the same WHERE the builder accumulated.
        """
        group_by = [c for c in (group_by or []) if c in COLUMNS]
        if not self._path.exists() or not group_by:
            return pd.DataFrame()
        cols = ", ".join(f'"{c}"' for c in group_by)
        src = f"read_parquet('{self._path.as_posix()}')"
        sql = f"""
            SELECT {cols},
                count(*)                       AS "Seats",
                count(DISTINCT "Institute")    AS "Colleges",
                count(DISTINCT "Branch")       AS "Branches",
                min("OpeningRank")             AS "BestOpening",
                min("ClosingRank")             AS "BestClosing",
                round(median("ClosingRank"))::BIGINT AS "MedianClosing",
                round(avg("ClosingRank"))::BIGINT    AS "AvgClosing",
                max("ClosingRank")             AS "WorstClosing"
            FROM {src}
        """
        if self._where:
            sql += " WHERE " + " AND ".join(self._where)
        sql += f" GROUP BY {cols} ORDER BY \"Seats\" DESC"
        with duckdb.connect() as con:
            return con.execute(sql, self._params).fetch_df()


def colleges_for_exam(exam: str, path: str | Path = DEFAULT_PATH) -> pd.DataFrame:
    """One row per college admitting through ``exam``, with aggregated detail.

    The whole aggregation runs in DuckDB (``GROUP BY Institute``) so only the
    small summary frame is materialized — never the full set of matching rows.
    Returns an empty DataFrame for a blank/unknown exam or a missing dataset.
    """
    path = Path(path)
    if not exam or not path.exists():
        return pd.DataFrame()
    src = f"read_parquet('{path.as_posix()}')"
    sql = f"""
        SELECT
            "Institute"                          AS "College",
            min("City")                          AS "City",
            min("State")                         AS "State",
            string_agg(DISTINCT "Program", ', ') AS "Programs",
            count(DISTINCT "Branch")             AS "Branches",
            min("Year")                          AS "FirstYear",
            max("Year")                          AS "LastYear",
            min("OpeningRank")                   AS "BestOpening",
            min("ClosingRank")                   AS "BestClosing",
            max("ClosingRank")                   AS "WorstClosing",
            count(*)                             AS "Records",
            min("Website")                       AS "Website",
            min("SourceURL")                     AS "SourceURL"
        FROM {src}
        WHERE "Exam" = ?
        GROUP BY "Institute"
        ORDER BY "College"
    """
    with duckdb.connect() as con:
        return con.execute(sql, [exam]).fetch_df()


class SQLError(ValueError):
    """Raised for a rejected or malformed analyst SQL query."""


def run_sql(sql: str, path: str | Path = DEFAULT_PATH, *, limit: int = 5000) -> pd.DataFrame:
    """Run a read-only SELECT against the dataset, exposed as the ``cutoffs`` view.

    For the analyst SQL escape hatch. Only a single SELECT/WITH statement is
    allowed (no DDL/DML/multiple statements); a LIMIT is appended if absent so a
    careless query can't return millions of rows. Raises :class:`SQLError` on a
    rejected statement and surfaces DuckDB errors as ``SQLError`` too.
    """
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise SQLError("Enter a SELECT query.")
    low = text.lower()
    if not (low.startswith("select") or low.startswith("with")):
        raise SQLError("Only SELECT / WITH queries are allowed.")
    if ";" in text:
        raise SQLError("Only a single statement is allowed (no ';').")
    forbidden = ("attach", "copy", "install", "load", "pragma", "export",
                 "create", "insert", "update", "delete", "drop", "alter")
    if any(re.search(rf"\b{kw}\b", low) for kw in forbidden):
        raise SQLError("Only read-only queries are allowed.")
    if " limit " not in f" {low} ":
        text += f" LIMIT {int(limit)}"
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        with duckdb.connect() as con:
            con.execute(
                f"CREATE VIEW cutoffs AS SELECT * FROM read_parquet('{path.as_posix()}')"
            )
            return con.execute(text).fetch_df()
    except duckdb.Error as exc:
        raise SQLError(str(exc)) from exc


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
