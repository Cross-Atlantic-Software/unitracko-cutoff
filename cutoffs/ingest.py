"""Run selected sources and write the aggregated Parquet output.

This is the bridge the frontend calls when you click "Generate": pick sources
(all or some), pick a mode (cached vs latest), get one normalized Parquet file.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import cutoffs.adapters  # noqa: F401  (import populates the registry)
from cutoffs.registry import all_sources, get_source, source_names
from cutoffs.schema import empty_frame
from cutoffs.storage import DEFAULT_PATH, write_parquet

Mode = str  # "cached" | "latest"


def run(
    names: list[str] | None = None,
    mode: Mode = "cached",
    path: str | Path = DEFAULT_PATH,
) -> pd.DataFrame:
    """Generate the dataset.

    names: source names to include; None/empty => ALL registered sources.
    mode:  "cached" calls load_cached(); "latest" calls fetch_latest().
    Returns the aggregated, normalized DataFrame (also written to ``path``).
    """
    if names:
        sources = [get_source(n) for n in names]
    else:
        sources = all_sources()

    frames: list[pd.DataFrame] = []
    for src in sources:
        df = src.fetch_latest() if mode == "latest" else src.load_cached()
        frames.append(src.normalize(df))

    combined = (
        pd.concat(frames, ignore_index=True) if frames else empty_frame()
    )
    write_parquet(combined, path)
    return combined


def available() -> list[str]:
    """List registered source names (for the frontend's selector)."""
    return source_names()
