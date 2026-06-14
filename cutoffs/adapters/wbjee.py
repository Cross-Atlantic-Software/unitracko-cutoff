"""WBJEE adapter — West Bengal Joint Entrance Examinations Board.

Cutoffs are published as round-wise allotment reports. ``load_cached()`` serves a
curated representative snapshot; ``fetch_latest()`` defers to it until a live
parser is wired in.
"""
from __future__ import annotations

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.registry import register
from cutoffs.source import CutoffSource, SourceMeta


@register
class WBJEE(CutoffSource):
    meta = SourceMeta(
        name="wbjee",
        exam="WBJEE",
        level="UG",
        states=("West Bengal",),
        data_format="html",
    )

    def load_cached(self) -> pd.DataFrame:
        return self.normalize(read_bundled("wbjee_cached.csv"))

    def fetch_latest(self) -> pd.DataFrame:
        return self.load_cached()
