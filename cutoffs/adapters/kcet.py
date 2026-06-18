"""KCET adapter — Karnataka Examination Authority (state engineering).

Cutoffs are published as round-wise PDFs/portal pages. ``load_cached()`` serves
a curated representative snapshot; ``fetch_latest()`` defers to it until a live
PDF/portal parser is wired in (see cutoffs/adapters/_pdf.py for the framework).
"""
from __future__ import annotations

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.registry import register
from cutoffs.source import CutoffSource, SourceMeta


@register
class KCET(CutoffSource):
    meta = SourceMeta(
        name="kcet",
        exam="KCET",
        level="UG",
        states=("Karnataka",),
        data_format="pdf",
        body_label="KCET",
        website="https://cetonline.karnataka.gov.in/kea/",
        source_url="https://cetonline.karnataka.gov.in/kea/",
    )

    def load_cached(self) -> pd.DataFrame:
        return self.normalize(read_bundled("kcet_cached.csv"))

    def fetch_latest(self) -> pd.DataFrame:
        return self.load_cached()
