"""Parquet storage — one normalized columnar file is the join point.

Adapters write here; the DuckDB query layer reads from here. Writes go through
``normalize`` so the on-disk schema is always the canonical 13 columns.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from cutoffs.schema import COLUMNS, empty_frame, normalize

# Canonical location of the aggregated dataset.
DEFAULT_PATH = Path("data") / "cutoffs.parquet"


def write_parquet(df: pd.DataFrame, path: str | Path = DEFAULT_PATH) -> Path:
    """Normalize ``df`` and write it to ``path`` as Parquet. Returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(normalize(df), preserve_index=False)
    pq.write_table(table, path)
    return path


def append_parquet(df: pd.DataFrame, path: str | Path = DEFAULT_PATH) -> Path:
    """Concatenate ``df`` onto an existing Parquet file (or create it)."""
    path = Path(path)
    new = normalize(df)
    if path.exists():
        existing = read_parquet(path)
        combined = pd.concat([existing, new], ignore_index=True)
    else:
        combined = new
    return write_parquet(combined, path)


def read_parquet(path: str | Path = DEFAULT_PATH) -> pd.DataFrame:
    """Read the Parquet dataset back as a schema-conformant DataFrame.

    Missing file => an empty, schema-conformant frame (never raises).
    """
    path = Path(path)
    if not path.exists():
        return empty_frame()
    table = pq.read_table(path)
    return normalize(table.to_pandas())[COLUMNS]
