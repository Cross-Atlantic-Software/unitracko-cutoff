"""Indian Admission Cutoff Aggregator.

A pluggable tool that collects admission cutoff data from Indian counseling
bodies, normalizes it to a single schema, stores it as Parquet, and queries it
with DuckDB.
"""

from cutoffs.schema import COLUMNS, empty_frame, normalize
from cutoffs.source import CutoffSource, SourceMeta
from cutoffs.registry import register, get_source, all_sources, source_names

__all__ = [
    "COLUMNS",
    "empty_frame",
    "normalize",
    "CutoffSource",
    "SourceMeta",
    "register",
    "get_source",
    "all_sources",
    "source_names",
]
