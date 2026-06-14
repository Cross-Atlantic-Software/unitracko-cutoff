"""PDF cutoff parsing framework (pdfplumber, Camelot fallback).

Most state counseling bodies (MHT-CET, BCECE, KEA, ...) publish opening/closing
ranks as PDFs. ``parse_cutoff_pdf`` extracts every table with pdfplumber, then
reuses the same heuristic column->schema mapping as the HTML scraper, so a new
PDF source is a few lines (see mhtcet.py for a worked example).

Deliberately tolerant: a missing file, an image-only PDF, or an unparseable page
yields an empty schema-frame, never an exception.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from cutoffs.scrape import map_table
from cutoffs.schema import empty_frame, normalize


def _open(source: str | Path | bytes):
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - optional dependency
        return None
    try:
        if isinstance(source, (bytes, bytearray)):
            return pdfplumber.open(io.BytesIO(source))
        if not Path(source).exists():
            return None
        return pdfplumber.open(source)
    except Exception:  # noqa: BLE001
        return None


def extract_pdf_tables(source: str | Path | bytes) -> list[pd.DataFrame]:
    """Return every table found across all pages as DataFrames (header = row 0)."""
    pdf = _open(source)
    if pdf is None:
        return []
    frames: list[pd.DataFrame] = []
    try:
        with pdf:
            for page in pdf.pages:
                for raw in page.extract_tables() or []:
                    if not raw or len(raw) < 2:
                        continue
                    header = [str(c).strip() if c else "" for c in raw[0]]
                    body = raw[1:]
                    try:
                        frames.append(pd.DataFrame(body, columns=header))
                    except Exception:  # noqa: BLE001 - ragged rows
                        continue
    except Exception:  # noqa: BLE001
        return frames
    return frames


def parse_cutoff_pdf(source: str | Path | bytes, *, exam: str, body: str = "",
                     year: int | None = None, level: str | None = None,
                     state: str | None = None) -> pd.DataFrame:
    """Extract cutoff rows from a PDF, mapped onto the unified schema."""
    frames = []
    for tbl in extract_pdf_tables(source):
        mapped = map_table(tbl, exam=exam, body=body, year=year,
                           level=level, state=state)
        if not mapped.empty:
            frames.append(mapped)
    if not frames:
        return empty_frame()
    return normalize(pd.concat(frames, ignore_index=True))
