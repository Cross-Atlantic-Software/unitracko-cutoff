"""TS EAMCET adapter — Telangana (TGEAPCET) engineering admissions.

TSCHE publishes an institute-wise last-rank statement PDF per phase. The flat
category x gender table is parsed by the shared TS/AP last-rank parser
(:mod:`cutoffs.adapters._lastrank`). ``load_cached`` serves a bundled parsed
snapshot; ``fetch_latest`` re-parses the live PDF and falls back to cached.
"""
from __future__ import annotations

import logging

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._http import fetch
from cutoffs.adapters._lastrank import dedup_lastrank, parse_lastrank_pdf
from cutoffs.registry import register
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)

_PDF_SPECS = [
    {"url": "https://tgeapcetd.nic.in/files/TGEAPCET_2025_FINALPHASE_LASTRANKS.pdf",
     "year": 2025, "round": "Final Phase"},
]


@register
class TSEAMCET(CutoffSource):
    meta = SourceMeta(
        name="tseamcet",
        exam="TS EAMCET",
        level="UG",
        states=("Telangana",),
        data_format="pdf",
        body_label="TS EAMCET",
        website="https://tgeapcet.nic.in/",
        source_url="https://tgeapcetd.nic.in/",
    )

    def load_cached(self) -> pd.DataFrame:
        return dedup_lastrank(self.normalize(read_bundled("tseamcet_official.csv.gz")))

    def fetch_latest(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for spec in _PDF_SPECS:
            try:
                resp = fetch(spec["url"], timeout=90.0, retries=1)
                df = parse_lastrank_pdf(
                    resp.content, exam=self.meta.exam, body=self.meta.body_label,
                    state="Telangana", year=spec["year"], round_label=spec["round"],
                    source_url=spec["url"])
                if not df.empty:
                    frames.append(df)
            except Exception as exc:  # noqa: BLE001 — one bad PDF never blocks the rest
                _log.debug("tseamcet fetch_latest skipped %s: %s", spec["url"], exc)
        if not frames:
            return self.load_cached()
        return dedup_lastrank(pd.concat(frames, ignore_index=True))
