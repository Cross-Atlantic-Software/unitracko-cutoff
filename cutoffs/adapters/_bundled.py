"""Helper for adapters to read their bundled 'cached' dataset."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def read_bundled(filename: str) -> pd.DataFrame:
    """Read a bundled CSV shipped under cutoffs/data/."""
    return pd.read_csv(_DATA_DIR / filename, dtype=str)
