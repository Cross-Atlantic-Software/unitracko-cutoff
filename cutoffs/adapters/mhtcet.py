"""MHT-CET adapter — Maharashtra CET Cell (state engineering admissions).

The official cutoffs are published as CAP-round PDFs on the CET Cell portal. Each
PDF is a per-institute, per-course block: a 5-digit institute line
(``01002 - Government College of Engineering, Amravati``), a 10-digit course line
(``0100219110 - Civil Engineering``), then a table whose header row is the
reservation-stage codes (GOPENS/GSCS/GSTS/.. EWS) and whose body rows are CAP
stages (I, II, ..), each cell a ``closing_rank\\n(percentile)``.

``parse_mhtcet_pdf`` parses that into the unified schema, associating each table
with the nearest course AND institute headers above it (so blocks that span page
breaks attribute correctly). ``load_cached`` serves a bundled parsed snapshot;
``fetch_latest`` re-parses the live CAP PDFs and falls back to cached.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.adapters._http import fetch
from cutoffs.registry import register
from cutoffs.schema import empty_frame, normalize
from cutoffs.source import CutoffSource, SourceMeta

_log = logging.getLogger(__name__)

# Official CAP-round cutoff PDFs (same layout, one parser covers all). Add a round
# here and it flows straight through.
_PDF_SPECS = [
    {"url": "https://fe2025.mahacet.org/2024/2024ENGG_CAP1_CutOff.pdf",
     "year": 2024, "round": "CAP1"},
]

_INST_RE = re.compile(r"^(\d{5})\s*-\s*(.+?)\s*$")
_COURSE_RE = re.compile(r"^(\d{10})\s*-\s*(.+?)\s*$")
_CELL_RE = re.compile(r"^\s*(\d+)")  # leading integer = closing rank
_DEDUP_COLS = ["Institute", "Branch", "Category", "Round", "Year", "ClosingRank"]


def _pdf_to_records(data: bytes, *, year: int, round_label: str,
                    source_url: str) -> list[dict]:
    """Parse one MHT-CET CAP PDF (bytes) into unified-schema dict rows."""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - optional dependency
        return []
    records: list[dict] = []
    inst: tuple[str, str] | None = None    # (code, name) carried across pages
    course: tuple[str, str] | None = None  # (code, branch) carried across pages
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                markers = []  # (top, kind, code, text)
                for line in page.extract_text_lines() or []:
                    text = line["text"]
                    mc = _COURSE_RE.match(text)
                    if mc:
                        markers.append((line["top"], "course", mc.group(1), mc.group(2)))
                        continue
                    mi = _INST_RE.match(text)
                    if mi:
                        markers.append((line["top"], "inst", mi.group(1), mi.group(2)))
                for table in page.find_tables() or []:
                    top = table.bbox[1]
                    above = [m for m in markers if m[0] <= top + 2]
                    courses = [m for m in above if m[1] == "course"]
                    insts = [m for m in above if m[1] == "inst"]
                    if courses:
                        c = max(courses, key=lambda m: m[0])
                        course = (c[2], c[3])
                    if insts:
                        i = max(insts, key=lambda m: m[0])
                        inst = (i[2], i[3])
                    if inst is None or course is None:
                        continue
                    grid = table.extract()
                    if not grid or not grid[0]:
                        continue
                    cats = [(c or "").replace("\n", "").strip() for c in grid[0][1:]]
                    for row in grid[1:]:
                        stage = (row[0] or "").strip()
                        rnd = f"{round_label} Stage {stage}" if stage else round_label
                        for cat, val in zip(cats, row[1:]):
                            m = _CELL_RE.match((val or "").strip())
                            if not m or not cat:
                                continue
                            records.append({
                                "Body": "MHT-CET", "Exam": "MHT-CET", "Level": "UG",
                                "State": "Maharashtra", "Institute": inst[1],
                                "Branch": course[1], "Category": cat, "Round": rnd,
                                "Year": year, "ClosingRank": int(m.group(1)),
                                "SourceURL": source_url,
                            })
    except Exception:  # noqa: BLE001 — a malformed page never sinks the parse
        return records
    return records


def parse_mhtcet_pdf(data: bytes, *, year: int, round_label: str,
                     source_url: str) -> pd.DataFrame:
    """Parse one MHT-CET CAP PDF into a normalized unified-schema DataFrame."""
    records = _pdf_to_records(data, year=year, round_label=round_label,
                              source_url=source_url)
    if not records:
        return empty_frame()
    return normalize(pd.DataFrame(records))


def _dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate cutoff rows (same college/branch/category/round/year/rank)."""
    if df.empty:
        return df
    cols = [c for c in _DEDUP_COLS if c in df.columns]
    return df.drop_duplicates(subset=cols).reset_index(drop=True)


@register
class MHTCET(CutoffSource):
    meta = SourceMeta(
        name="mhtcet",
        exam="MHT-CET",
        level="UG",
        states=("Maharashtra",),
        data_format="pdf",
        body_label="MHT-CET",
        website="https://cetcell.mahacet.org/",
        source_url="https://fe2024.mahacet.org/StaticPages/HTML_FrmInstituteCutOff.aspx",
    )

    def load_cached(self) -> pd.DataFrame:
        """The bundled parsed official snapshot (real CET Cell CAP cutoff data)."""
        return _dedup(self.normalize(read_bundled("mhtcet_official.csv.gz")))

    def fetch_latest(self) -> pd.DataFrame:
        """Re-parse the live official CAP PDFs; fall back to cached on failure."""
        frames: list[pd.DataFrame] = []
        for spec in _PDF_SPECS:
            try:
                resp = fetch(spec["url"], timeout=90.0, retries=1)
                df = parse_mhtcet_pdf(resp.content, year=spec["year"],
                                      round_label=spec["round"], source_url=spec["url"])
                if not df.empty:
                    frames.append(df)
            except Exception as exc:  # noqa: BLE001 — one bad PDF never blocks the rest
                _log.debug("mhtcet fetch_latest skipped %s: %s", spec["url"], exc)
        if not frames:
            return self.load_cached()
        return _dedup(pd.concat(frames, ignore_index=True))
