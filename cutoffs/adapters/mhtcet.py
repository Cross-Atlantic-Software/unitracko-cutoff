"""MHT-CET adapter — Maharashtra CET Cell (state engineering admissions).

The official cutoffs are published as CAP round PDFs. This is the worked PDF
example: ``fetch_latest()`` downloads the configured cutoff PDF and parses it
with pdfplumber (``cutoffs.adapters._pdf``), falling back to the bundled curated
snapshot on any problem (no URL set, network error, image-only PDF, parse miss),
so the body is always usable.
"""

from __future__ import annotations

import httpx
import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._pdf import parse_cutoff_pdf
from cutoffs.registry import register
from cutoffs.source import CutoffSource, SourceMeta

# Official CAP cutoff PDFs are published per round on the CET Cell portal. Set a
# concrete round PDF URL here (or pass one to fetch_latest) to pull live data.
_CUTOFF_PDF_URL = ""
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


@register
class MHTCET(CutoffSource):
    meta = SourceMeta(
        name="mhtcet",
        exam="MHT-CET",
        level="UG",
        states=("Maharashtra",),
        data_format="pdf",
    )

    #: Set to a concrete CAP-round cutoff PDF URL to pull live data.
    pdf_url: str = _CUTOFF_PDF_URL

    def load_cached(self) -> pd.DataFrame:
        return self.normalize(read_bundled("mhtcet_cached.csv"))

    def fetch_latest(self) -> pd.DataFrame:
        """Download + parse the official cutoff PDF; fall back to cached."""
        if not self.pdf_url:
            return self.load_cached()
        try:
            resp = httpx.get(self.pdf_url, headers=_HEADERS, timeout=30,
                             follow_redirects=True)
            resp.raise_for_status()
            df = parse_cutoff_pdf(resp.content, exam=self.meta.exam,
                                  body="MHT-CET", level="UG", state="Maharashtra")
            df = self.normalize(df)
            if not df.empty:
                return df
        except Exception:
            pass
        return self.load_cached()
