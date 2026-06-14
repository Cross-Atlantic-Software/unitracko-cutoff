"""Parser for KEAM (Kerala CEE) last-rank PDFs — a pivoted matrix layout.

KEAM publishes last-rank tables as: a branch name section header, then a table
whose rows are colleges and whose columns are reservation categories (SM, EZ,
MU, …), each cell being that category's last (closing) rank. This un-pivots that
matrix into the unified one-row-per (college, branch, category) schema.

Run:  python scripts/parse_keam.py  [pdf_url]
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import httpx
import pandas as pd

from cutoffs.schema import normalize

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "https://cee.kerala.gov.in/keam2025/list/lastrank/eng-trial.pdf"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# Kerala reservation category codes that appear as column headers.
_CAT_CODES = {"SM", "EZ", "MU", "LA", "DV", "VK", "BH", "BX", "KN", "KU",
              "SC", "ST", "EW", "FW", "DK", "KO", "BP", "GU", "TM"}


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v).replace("\n", " ")).strip() if v is not None else ""


def _is_rank(v: str) -> bool:
    return bool(re.fullmatch(r"\d{1,6}", v.replace(",", "")))


def parse_keam_pdf(content: bytes, *, exam: str, body: str = "CEE Kerala",
                   stream: str = "Engineering", year: int = 2025) -> pd.DataFrame:
    """Un-pivot a KEAM last-rank matrix PDF into the unified schema."""
    import pdfplumber

    rows: list[dict] = []
    branch = ""
    cats: list[tuple[int, str]] = []  # (column index, category code)
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for raw in table:
                    cells = [_clean(c) for c in raw]
                    nonempty = [c for c in cells if c]
                    if not nonempty:
                        continue
                    # Column header row defines the category columns.
                    if any("name of college" in c.lower() for c in cells):
                        cats = [(i, c.upper()) for i, c in enumerate(cells)
                                if c.upper() in _CAT_CODES]
                        continue
                    # Branch section header: a single meaningful cell, no ranks.
                    if len(nonempty) == 1 and not _is_rank(nonempty[0]):
                        branch = nonempty[0]
                        continue
                    if not cats:
                        continue
                    # Data row: college name is the longest text cell; un-pivot ranks.
                    text_cells = [c for c in cells if c and not _is_rank(c)
                                  and c.upper() not in {"G", "A", "S", "P", "N"}]
                    college = max(text_cells, key=len) if text_cells else ""
                    if not college or len(college) < 4:
                        continue
                    for idx, code in cats:
                        if idx < len(cells):
                            val = cells[idx].replace(",", "")
                            if _is_rank(val):
                                rows.append({
                                    "Body": body, "Exam": exam, "Level": "UG",
                                    "State": "Kerala", "Year": year, "Round": "Trial",
                                    "Institute": college, "Branch": branch,
                                    "Category": code, "Quota": "State",
                                    "Gender": "Gender-Neutral",
                                    "OpeningRank": pd.NA, "ClosingRank": int(val),
                                })
    return normalize(pd.DataFrame(rows)) if rows else normalize(pd.DataFrame())


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else DEFAULT_URL
    r = httpx.get(url, headers=HEADERS, timeout=40, follow_redirects=True, verify=False)
    df = parse_keam_pdf(r.content, exam="Kerala Engineering Architecture Medical Entrance Examination")
    out = ROOT / "data" / "keam_harvested.parquet"
    df.to_parquet(out, index=False)
    print(f"KEAM parsed: {len(df)} rows | {df['Institute'].nunique()} colleges | "
          f"{df['Branch'].nunique()} branches | {df['Category'].nunique()} categories")
    with pd.option_context("display.width", 200, "display.max_colwidth", 36):
        print(df[["Institute", "Branch", "Category", "ClosingRank"]].head(8).to_string(index=False))
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
