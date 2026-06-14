"""Bihar Polytechnic (DCECE) adapter — BCECE Board.

REAL data: BCECE publishes the polytechnic opening/closing ranks as a tidy PDF
that the generic pdfplumber parser handles directly. ``fetch_latest()`` downloads
and parses it live; ``load_cached()`` serves a bundled snapshot (~430 rows across
58 Bihar polytechnic colleges).
"""
from __future__ import annotations

import httpx
import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._pdf import parse_cutoff_pdf
from cutoffs.registry import register
from cutoffs.source import CutoffSource, SourceMeta

_CUTOFF_PDF = "https://bceceboard.bihar.gov.in/pdf_Web/DC_PE25_FOCFF.pdf"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


@register
class BiharPolytechnic(CutoffSource):
    meta = SourceMeta(
        name="biharpoly",
        exam="Bihar Polytechnic Common Entrance Competitive Examination",
        level="Diploma",
        states=("Bihar",),
        data_format="pdf",
    )

    def load_cached(self) -> pd.DataFrame:
        return self.normalize(read_bundled("biharpoly_cached.csv"))

    def fetch_latest(self) -> pd.DataFrame:
        try:
            resp = httpx.get(_CUTOFF_PDF, headers=_HEADERS, timeout=40,
                             follow_redirects=True, verify=False)
            resp.raise_for_status()
            df = self.normalize(parse_cutoff_pdf(
                resp.content, exam=self.meta.exam, body="BCECE",
                level="Diploma", state="Bihar"))
            if not df.empty:
                return df
        except Exception:
            pass
        return self.load_cached()
