"""KEAM adapter — CEE Kerala (Kerala Engineering/Architecture/Medical).

REAL data: KEAM publishes last-rank tables as pivoted-matrix PDFs (colleges as
rows, reservation categories as columns). ``fetch_latest()`` downloads the
official PDF and un-pivots it into the unified schema; ``load_cached()`` serves a
bundled snapshot parsed the same way (4k+ rows across ~140 Kerala colleges).
"""
from __future__ import annotations

import io
import logging
import re

import httpx
import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.registry import register
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)

_LASTRANK_PDF = "https://cee.kerala.gov.in/keam2025/list/lastrank/eng-trial.pdf"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_CAT_CODES = {"SM", "EZ", "MU", "LA", "DV", "VK", "BH", "BX", "KN", "KU",
              "SC", "ST", "EW", "FW", "DK", "KO", "BP", "GU", "TM"}


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v).replace("\n", " ")).strip() if v is not None else ""


def _is_rank(v: str) -> bool:
    return bool(re.fullmatch(r"\d{1,6}", v.replace(",", "")))


def parse_keam_pdf(content: bytes, *, exam: str, year: int = 2025) -> pd.DataFrame:
    """Un-pivot a KEAM last-rank matrix PDF into the unified schema."""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover
        return pd.DataFrame()
    rows, branch, cats = [], "", []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    for raw in table:
                        cells = [_clean(c) for c in raw]
                        nonempty = [c for c in cells if c]
                        if not nonempty:
                            continue
                        if any("name of college" in c.lower() for c in cells):
                            cats = [(i, c.upper()) for i, c in enumerate(cells)
                                    if c.upper() in _CAT_CODES]
                            continue
                        if len(nonempty) == 1 and not _is_rank(nonempty[0]):
                            branch = nonempty[0]
                            continue
                        if not cats:
                            continue
                        text_cells = [c for c in cells if c and not _is_rank(c)
                                      and c.upper() not in {"G", "A", "S", "P", "N"}]
                        college = max(text_cells, key=len) if text_cells else ""
                        if not college or len(college) < 4:
                            continue
                        for idx, code in cats:
                            if idx < len(cells) and _is_rank(cells[idx].replace(",", "")):
                                rows.append({
                                    "Body": "CEE Kerala", "Exam": exam, "Level": "UG",
                                    "State": "Kerala", "Year": year, "Round": "Trial",
                                    "Institute": college, "Branch": branch,
                                    "Category": code, "Quota": "State",
                                    "Gender": "Gender-Neutral", "OpeningRank": pd.NA,
                                    "ClosingRank": int(cells[idx].replace(",", "")),
                                })
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    return pd.DataFrame(rows)


@register
class KEAM(CutoffSource):
    meta = SourceMeta(
        name="keam",
        exam="Kerala Engineering Architecture Medical Entrance Examination",
        level="UG",
        states=("Kerala",),
        data_format="pdf",
    )

    def load_cached(self) -> pd.DataFrame:
        return self.normalize(read_bundled("keam_cached.csv"))

    def fetch_latest(self) -> pd.DataFrame:
        try:
            resp = httpx.get(_LASTRANK_PDF, headers=_HEADERS, timeout=40,
                             follow_redirects=True)
            resp.raise_for_status()
            df = self.normalize(parse_keam_pdf(resp.content, exam=self.meta.exam))
            if not df.empty:
                return df
        except Exception as exc:
            _log.debug("keam fetch_latest fell back to cached: %s", exc)
        return self.load_cached()
