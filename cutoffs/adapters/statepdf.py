"""State/board PDF cutoff adapters harvested from official direct-PDF links.

Each body ships a real bundled snapshot (parsed from the official cutoff PDF) and
re-parses the live PDF on ``fetch_latest()``. They share one base since the shape
is identical: load bundled CSV, else download + pdfplumber-parse the official PDF.
"""
from __future__ import annotations

import httpx
import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._pdf import parse_cutoff_pdf
from cutoffs.registry import register
from cutoffs.source import CutoffSource, SourceMeta

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


class _BundledPDFSource(CutoffSource):
    """Base: bundled real snapshot + best-effort live PDF re-parse."""

    # Placeholder so the ABC's concrete-subclass check passes; real subclasses
    # override meta + the three attributes below.
    meta = SourceMeta(name="_pdfbase", exam="_", level="UG")
    cached_csv: str = ""
    pdf_url: str = ""
    body_label: str = ""

    def load_cached(self) -> pd.DataFrame:
        return self.normalize(read_bundled(self.cached_csv))

    def fetch_latest(self) -> pd.DataFrame:
        if not self.pdf_url:
            return self.load_cached()
        try:
            resp = httpx.get(self.pdf_url, headers=_HEADERS, timeout=45,
                             follow_redirects=True, verify=False)
            resp.raise_for_status()
            state = self.meta.states[0] if self.meta.states else "All India"
            df = self.normalize(parse_cutoff_pdf(
                resp.content, exam=self.meta.exam, body=self.body_label,
                level=self.meta.level, state=state))
            if not df.empty:
                return df
        except Exception:
            pass
        return self.load_cached()


@register
class RajasthanPolytechnic(_BundledPDFSource):
    meta = SourceMeta(name="rajpoly",
                      exam="Rajasthan Polytechnic Entrance Examination",
                      level="Diploma", states=("Rajasthan",), data_format="pdf")
    cached_csv = "rajpoly_cached.csv"
    body_label = "Rajasthan DTE"
    pdf_url = ("https://dte.rajasthan.gov.in/assets/docs/Admission/FirstYearEngg/"
               "Final%20Merit%20List-%20first%20Allotment%20%202024-25.pdf")


@register
class KeralaVeterinary(_BundledPDFSource):
    meta = SourceMeta(name="keralavet",
                      exam="Kerala Veterinary Entrance Examination",
                      level="UG", states=("Kerala",), data_format="pdf")
    cached_csv = "keralavet_cached.csv"
    body_label = "CEE Kerala"
    pdf_url = "https://cee.kerala.gov.in/keam2025/list/allot/allied_p1_final.pdf"


@register
class ICARAIEEA(_BundledPDFSource):
    meta = SourceMeta(
        name="icar",
        exam="Indian Council of Agricultural Research All India Entrance "
             "Examination for Admission Undergraduate",
        level="UG", states=(), data_format="pdf")
    cached_csv = "icar_cached.csv"
    body_label = "ICAR / NTA"
    pdf_url = "https://icarcounseling.com/Images/ICAR-UG-Counseling-CUT-OFF-2024.pdf"


@register
class BiharEngineering(_BundledPDFSource):
    meta = SourceMeta(name="bihareng",
                      exam="Bihar Engineering Entrance Examination",
                      level="UG", states=("Bihar",), data_format="pdf")
    cached_csv = "bihareng_cached.csv"
    body_label = "BCECE (UGEAC)"
    pdf_url = "https://bceceboard.bihar.gov.in/pdf_Web/UGEAC2024_FOCRANK.pdf"
