"""AP EAPCET adapter — Andhra Pradesh (APEAPCET / AP EAMCET) engineering.

APSCHE publishes an institute-wise last-rank-details PDF. The flat category x gender
table is parsed by the shared TS/AP last-rank parser
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
    {"url": "https://apsche.ap.gov.in/Pdf/APEAMCET2022LASTRANKDETAILS.pdf",
     "year": 2022, "round": "Final"},
]


@register
class APEAPCET(CutoffSource):
    meta = SourceMeta(
        name="apeapcet",
        exam="AP EAPCET",
        level="UG",
        states=("Andhra Pradesh",),
        data_format="pdf",
        body_label="AP EAPCET",
        website="https://cets.apsche.ap.gov.in/",
        source_url="https://apsche.ap.gov.in/",
    )

    def load_cached(self) -> pd.DataFrame:
        return dedup_lastrank(self.normalize(read_bundled("apeapcet_official.csv.gz")))

    def fetch_latest(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for spec in _PDF_SPECS:
            try:
                resp = fetch(spec["url"], timeout=90.0, retries=1)
                df = parse_lastrank_pdf(
                    resp.content, exam=self.meta.exam, body=self.meta.body_label,
                    state="Andhra Pradesh", year=spec["year"],
                    round_label=spec["round"], source_url=spec["url"])
                if not df.empty:
                    frames.append(df)
            except Exception as exc:  # noqa: BLE001 — one bad PDF never blocks the rest
                _log.debug("apeapcet fetch_latest skipped %s: %s", spec["url"], exc)
        if not frames:
            return self.load_cached()
        return dedup_lastrank(pd.concat(frames, ignore_index=True))
