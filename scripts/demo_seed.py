"""Seed a small sample dataset so you can SEE the project's output shape.

This is a stand-in for the real adapters (Phase 2). It writes the canonical
Parquet file and also dumps a CSV you can open in Excel.

Run:  python scripts/demo_seed.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cutoffs.query import CutoffQuery
from cutoffs.schema import COLUMNS
from cutoffs.storage import read_parquet, write_parquet

PARQUET = Path("data") / "cutoffs.parquet"
CSV = Path("data") / "cutoffs.csv"

SAMPLE = [
    ("JoSAA", "JEE Advanced", "UG", "All India", 2024, "1", "IIT Bombay",
     "Computer Science and Engineering", "OPEN", "AI", "Gender-Neutral", 1, 66),
    ("JoSAA", "JEE Advanced", "UG", "All India", 2024, "1", "IIT Delhi",
     "Computer Science and Engineering", "OPEN", "AI", "Gender-Neutral", 67, 110),
    ("JoSAA", "JEE Advanced", "UG", "All India", 2024, "2", "IIT Madras",
     "Electrical Engineering", "OBC-NCL", "AI", "Gender-Neutral", 500, 1200),
    ("MHT-CET", "MHT-CET", "UG", "Maharashtra", 2024, "1", "COEP Pune",
     "Computer Engineering", "OPEN", "HS", "Gender-Neutral", 10, 350),
]


def main() -> None:
    df = pd.DataFrame(SAMPLE, columns=COLUMNS)
    write_parquet(df, PARQUET)
    read_parquet(PARQUET).to_csv(CSV, index=False)

    print(f"Wrote {len(df)} rows -> {PARQUET}")
    print(f"Wrote a human-readable copy -> {CSV}\n")

    print("All rows (sorted by ClosingRank via DuckDB):")
    print(CutoffQuery(PARQUET).to_df().to_string(index=False))

    print("\nExample filter - JoSAA, Round 1 only:")
    got = CutoffQuery(PARQUET).where("Body", "JoSAA").where("Round", "1").to_df()
    print(got[["Institute", "Branch", "OpeningRank", "ClosingRank"]].to_string(index=False))


if __name__ == "__main__":
    main()
