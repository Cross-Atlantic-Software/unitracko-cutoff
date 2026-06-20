"""Bihar Polytechnic (DCECE) adapter — BCECE Board.

REAL data: BCECE publishes the polytechnic opening/closing ranks as a tidy PDF
that the generic pdfplumber parser handles directly. ``fetch_latest()`` downloads
and parses it live; ``load_cached()`` serves a bundled snapshot (~430 rows across
58 Bihar polytechnic colleges).
"""
from __future__ import annotations

import logging

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._http import fetch
from cutoffs.adapters._pdf import parse_cutoff_pdf
from cutoffs.registry import register
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)

_CUTOFF_PDF = "https://bceceboard.bihar.gov.in/pdf_Web/DC_PE25_FOCFF.pdf"


@register
class BiharPolytechnic(CutoffSource):
    meta = SourceMeta(
        name="biharpoly",
        exam="Bihar Polytechnic Common Entrance Competitive Examination",
        level="Diploma",
        states=("Bihar",),
        data_format="pdf",
        body_label="BCECE",
        website="https://bceceboard.bihar.gov.in/",
        source_url=_CUTOFF_PDF,
    )

    def load_cached(self) -> pd.DataFrame:
        df = self.normalize(read_bundled("biharpoly_cached.csv"))
        df["Body"] = self.meta.body_label     # match fetch_latest's label
        df["Year"] = df["Year"].fillna(2025)   # DCECE 2025 snapshot
        return df

    def fetch_latest(self) -> pd.DataFrame:
        try:
            resp = fetch(_CUTOFF_PDF, timeout=40)
            df = self.normalize(parse_cutoff_pdf(
                resp.content, exam=self.meta.exam, body=self.meta.body_label,
                level=self.meta.level, state="Bihar"))
            if not df.empty:
                return df
        except Exception as exc:
            _log.debug("biharpoly fetch_latest fell back to cached: %s", exc)
        return self.load_cached()
