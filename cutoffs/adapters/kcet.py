"""KCET adapter — Karnataka Examination Authority (state engineering).

KEA publishes round-wise engineering cutoffs as PDFs whose layout is a per-college
matrix: a ``N E### College Name`` header line, then a table whose header row is the
reservation-category codes (GM/SC/ST/1/2A/.. with region/medium suffixes) and whose
body rows are branches, each cell a closing rank.

``parse_kcet_pdf`` parses that structure into the unified schema (associating each
table with the nearest college header *above* it by y-position, so a college whose
table spills across a page boundary is still attributed correctly). ``load_cached``
serves a bundled parsed snapshot (``kcet_official.csv``) plus the small curated
multi-year sample; ``fetch_latest`` re-parses the live PDFs and falls back to cached.
"""
from __future__ import annotations

import io
import re

import pandas as pd

from cutoffs.adapters._bundled import read_bundled
from cutoffs.registry import register
from cutoffs.schema import empty_frame, normalize
from cutoffs.source import CutoffSource, SourceMeta

# Official round-wise cutoff PDFs. Same layout, so one parser covers all; add a
# round/quota here and it flows straight through. ``quota`` distinguishes the
# general state pool ("Karnataka") from the Kalyana-/Hyderabad-Karnataka pool.
_PDF_BASE = "https://cetonline.karnataka.gov.in/keawebentry456/ugcet2024/"
_PDF_SPECS = [
    {"file": "ENGG_CUTOFF_2024_r1_gen_prov.pdf", "year": 2024, "round": "1",
     "quota": "General"},
    {"file": "ENGG_CUTOFF_2024_r1_hk_prov.pdf", "year": 2024, "round": "1",
     "quota": "Kalyana-Karnataka"},
]

# A college header: leading serial, the E-code, then the name (possibly with a
# trailing "( PUBLIC UNIV. )"-style tag).
_COLLEGE_RE = re.compile(r"^\s*\d+\s+(E\d{3,4})\s+(.+?)\s*$")
_RANK_RE = re.compile(r"^\d+$")
# The deduplication key for a parsed cutoff cell.
_DEDUP_COLS = ["Institute", "Branch", "Category", "Quota", "Year", "ClosingRank"]


def _pdf_to_records(data: bytes, *, year: int, round_label: str, quota: str,
                    source_url: str) -> list[dict]:
    """Parse one KEA cutoff PDF (bytes) into unified-schema dict rows."""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - optional dependency
        return []
    records: list[dict] = []
    current: tuple[str, str] | None = None  # (code, name) carried across pages
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                heads = []
                for line in page.extract_text_lines() or []:
                    m = _COLLEGE_RE.match(line["text"])
                    if m:
                        heads.append((line["top"], m.group(1), m.group(2).strip()))
                for table in page.find_tables() or []:
                    above = [h for h in heads if h[0] <= table.bbox[1] + 2]
                    if above:
                        top = max(above, key=lambda h: h[0])
                        current = (top[1], top[2])
                    if current is None:
                        continue
                    grid = table.extract()
                    if not grid or not grid[0]:
                        continue
                    cats = [(c or "").strip() for c in grid[0][1:]]
                    for row in grid[1:]:
                        branch = (row[0] or "").replace("\n", " ").strip()
                        if not branch:
                            continue
                        for cat, val in zip(cats, row[1:]):
                            v = (val or "").strip()
                            if not _RANK_RE.match(v):
                                continue
                            records.append({
                                "Body": "KCET", "Exam": "KCET", "Level": "UG",
                                "State": "Karnataka", "Institute": current[1],
                                "Branch": branch, "Category": cat, "Quota": quota,
                                "Round": round_label, "Year": year,
                                "ClosingRank": int(v), "SourceURL": source_url,
                            })
    except Exception:  # noqa: BLE001 — a malformed page never sinks the parse
        return records
    return records


def parse_kcet_pdf(data: bytes, *, year: int, round_label: str, quota: str,
                   source_url: str) -> pd.DataFrame:
    """Parse one KEA cutoff PDF into a normalized unified-schema DataFrame."""
    records = _pdf_to_records(data, year=year, round_label=round_label,
                              quota=quota, source_url=source_url)
    if not records:
        return empty_frame()
    return normalize(pd.DataFrame(records))


def _dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate cutoff rows (same college/branch/category/quota/year/rank)."""
    if df.empty:
        return df
    cols = [c for c in _DEDUP_COLS if c in df.columns]
    return df.drop_duplicates(subset=cols).reset_index(drop=True)


@register
class KCET(CutoffSource):
    meta = SourceMeta(
        name="kcet",
        exam="KCET",
        level="UG",
        states=("Karnataka",),
        data_format="pdf",
        body_label="KCET",
        website="https://cetonline.karnataka.gov.in/kea/",
        source_url="https://cetonline.karnataka.gov.in/kea/",
    )

    def load_cached(self) -> pd.DataFrame:
        """Bundled parsed official snapshot + the small curated multi-year sample."""
        frames = [self.normalize(read_bundled("kcet_cached.csv"))]
        try:
            frames.append(self.normalize(read_bundled("kcet_official.csv.gz")))
        except (FileNotFoundError, OSError):  # snapshot not generated yet
            pass
        return _dedup(pd.concat(frames, ignore_index=True))

    def fetch_latest(self) -> pd.DataFrame:
        """Re-parse the live official PDFs; fall back to cached on any failure."""
        from cutoffs.adapters._http import fetch

        frames: list[pd.DataFrame] = []
        for spec in _PDF_SPECS:
            url = _PDF_BASE + spec["file"]
            try:
                resp = fetch(url, timeout=60.0, retries=1)
                df = parse_kcet_pdf(resp.content, year=spec["year"],
                                    round_label=spec["round"], quota=spec["quota"],
                                    source_url=url)
                if not df.empty:
                    frames.append(df)
            except Exception:  # noqa: BLE001 — one bad PDF never blocks the rest
                continue
        if not frames:
            return self.load_cached()
        # Keep the curated multi-year sample alongside the live official rows.
        frames.append(self.normalize(read_bundled("kcet_cached.csv")))
        return _dedup(pd.concat(frames, ignore_index=True))
