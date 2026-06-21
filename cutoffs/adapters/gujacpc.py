"""Gujarat ACPC adapter — Admission Committee for Professional Courses, Gujarat.

ACPC publishes a flat branch-wise closing-rank PDF for degree engineering:
Inst_Name / Course_name / Alloted_Cat / Quota / Institute Type / First Rank /
Last Rank — one row per (institute, course, category, quota). Parsed by the shared
flat-cutoff parser (:mod:`cutoffs.adapters._flattable`). ``load_cached`` serves a
bundled parsed snapshot; ``fetch_latest`` re-parses the live PDF.
"""
from __future__ import annotations

import logging

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._flattable import dedup_flat, parse_flat_cutoff
from cutoffs.adapters._http import fetch
from cutoffs.registry import register
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)

_PDF_SPECS = [
    {"url": "https://acpc.gujarat.gov.in/assets/uploads/media-uploader/branch-wise-cut-off1718193325.pdf",
     "year": 2024, "round": "Mock Round"},
]
_COLMAP = [
    ("inst_name", "Institute"), ("inst name", "Institute"),
    ("course", "Branch"), ("alloted_cat", "Category"), ("cat", "Category"),
    ("quota", "Quota"), ("first rank", "OpeningRank"), ("last rank", "ClosingRank"),
]


@register
class GujaratACPC(CutoffSource):
    meta = SourceMeta(
        name="gujacpc",
        exam="Gujarat ACPC",
        level="UG",
        states=("Gujarat",),
        data_format="pdf",
        body_label="Gujarat ACPC",
        website="https://acpc.gujarat.gov.in/",
        source_url="https://acpc.gujarat.gov.in/",
    )

    def load_cached(self) -> pd.DataFrame:
        return dedup_flat(self.normalize(read_bundled("gujacpc_official.csv.gz")))

    def fetch_latest(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for spec in _PDF_SPECS:
            try:
                resp = fetch(spec["url"], timeout=90.0, retries=1)
                df = parse_flat_cutoff(
                    resp.content, colmap=_COLMAP, body=self.meta.body_label,
                    exam=self.meta.exam, state="Gujarat", year=spec["year"],
                    round_label=spec["round"], source_url=spec["url"])
                if not df.empty:
                    frames.append(df)
            except Exception as exc:  # noqa: BLE001 — one bad PDF never blocks the rest
                _log.debug("gujacpc fetch_latest skipped %s: %s", spec["url"], exc)
        if not frames:
            return self.load_cached()
        return dedup_flat(pd.concat(frames, ignore_index=True))
