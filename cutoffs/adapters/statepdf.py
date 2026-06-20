"""State/board PDF cutoff adapters harvested from official direct-PDF links.

Each body ships a real bundled snapshot (parsed from the official cutoff PDF) and
re-parses the live PDF on ``fetch_latest()``. They share one base since the shape
is identical: load bundled CSV, else download + pdfplumber-parse the official PDF.
"""
from __future__ import annotations

import logging

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._http import fetch
from cutoffs.adapters._pdf import parse_cutoff_pdf
from cutoffs.registry import register
from cutoffs.schema import dedouble_rows
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)


class _BundledPDFSource(CutoffSource):
    """Base: bundled real snapshot + best-effort live PDF re-parse.

    Identity (Body label, links) lives on ``meta``; the live PDF fetched on
    refresh is ``meta.source_url``. Subclasses set ``meta`` + ``cached_csv``.
    """

    # Placeholder so the ABC's concrete-subclass check passes.
    meta = SourceMeta(name="_pdfbase", exam="_", level="UG")
    cached_csv: str = ""

    def _preprocess(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Hook to repair the raw (string) snapshot before normalization."""
        return raw

    def load_cached(self) -> pd.DataFrame:
        df = self.normalize(self._preprocess(read_bundled(self.cached_csv)))
        # Canonicalize Body so cached and fetch_latest agree on one label.
        if self.meta.body_label:
            df["Body"] = self.meta.body_label
        # Some merit-list PDFs publish a single list with no category split;
        # label the gap explicitly so those rows stay filterable, not invisible.
        df["Category"] = df["Category"].fillna("Unspecified")
        return df

    def fetch_latest(self) -> pd.DataFrame:
        if not self.meta.source_url:
            return self.load_cached()
        try:
            resp = fetch(self.meta.source_url, timeout=45)
            state = self.meta.states[0] if self.meta.states else "All India"
            df = self.normalize(parse_cutoff_pdf(
                resp.content, exam=self.meta.exam, body=self.meta.body_label,
                level=self.meta.level, state=state))
            if not df.empty:
                return df
        except Exception as exc:
            _log.debug("%s fetch_latest fell back to cached: %s",
                       self.meta.name, exc)
        return self.load_cached()


@register
class RajasthanPolytechnic(_BundledPDFSource):
    meta = SourceMeta(
        name="rajpoly", exam="Rajasthan Polytechnic Entrance Examination",
        level="Diploma", states=("Rajasthan",), data_format="pdf",
        body_label="Rajasthan DTE", website="https://dte.rajasthan.gov.in/",
        source_url=("https://dte.rajasthan.gov.in/assets/docs/Admission/FirstYearEngg/"
                    "Final%20Merit%20List-%20first%20Allotment%20%202024-25.pdf"))
    cached_csv = "rajpoly_cached.csv"

    def _preprocess(self, raw: pd.DataFrame) -> pd.DataFrame:
        # This snapshot mixes clean and glyph-doubled rows; de-double the doubled
        # ones whole (incl. rank digits) before coercion. See dedouble_rows.
        return dedouble_rows(raw, ("Institute", "Branch", "Category", "Gender"))


@register
class KeralaVeterinary(_BundledPDFSource):
    meta = SourceMeta(
        name="keralavet", exam="Kerala Veterinary Entrance Examination",
        level="UG", states=("Kerala",), data_format="pdf",
        body_label="CEE Kerala", website="https://cee.kerala.gov.in/",
        source_url="https://cee.kerala.gov.in/keam2025/list/allot/allied_p1_final.pdf")
    cached_csv = "keralavet_cached.csv"


@register
class ICARAIEEA(_BundledPDFSource):
    meta = SourceMeta(
        name="icar",
        exam="Indian Council of Agricultural Research All India Entrance "
             "Examination for Admission Undergraduate",
        level="UG", states=(), data_format="pdf",
        body_label="ICAR / NTA", website="https://icar.org.in/",
        source_url="https://icarcounseling.com/Images/ICAR-UG-Counseling-CUT-OFF-2024.pdf")
    cached_csv = "icar_cached.csv"


@register
class BiharEngineering(_BundledPDFSource):
    meta = SourceMeta(
        name="bihareng", exam="Bihar Engineering Entrance Examination",
        level="UG", states=("Bihar",), data_format="pdf",
        body_label="BCECE (UGEAC)", website="https://bceceboard.bihar.gov.in/",
        source_url="https://bceceboard.bihar.gov.in/pdf_Web/UGEAC2024_FOCRANK.pdf")
    cached_csv = "bihareng_cached.csv"
