"""One-shot builder for the full JoSAA OR-CR snapshot (cutoffs/data/).

Drives the cascading JoSAA archive form (see ``cutoffs.adapters._josaa_orcr``)
across the requested years, selecting "ALL" at every level so each (year, round)
yields the entire grid — ~130 institutes / ~1000 institute+program rows, far
beyond the old hand-curated stub. Output is gzipped CSV (pandas reads it back
transparently) so the committed snapshot stays small.

Run:  python scripts/scrape_josaa.py
      python scripts/scrape_josaa.py --years 2024 2025 --rounds all
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from cutoffs.adapters._josaa_orcr import scrape_archive

DATA = Path(__file__).resolve().parent.parent / "cutoffs" / "data"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Build the full JoSAA OR-CR snapshot.")
    ap.add_argument("--years", type=int, nargs="*", default=[2023, 2024, 2025])
    ap.add_argument("--rounds", choices=["ends", "all"], default="ends",
                    help="'ends' = round 1 + final round; 'all' = every round")
    ap.add_argument("--out", default=str(DATA / "josaa_cached.csv.gz"))
    args = ap.parse_args()

    df = scrape_archive(args.years, args.rounds)
    if df.empty:
        raise SystemExit("scrape produced no rows")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False,
              compression="gzip" if out.suffix == ".gz" else None)
    print(f"wrote {len(df):,} rows | {df['Institute'].nunique()} institutes | "
          f"years {sorted(df['Year'].unique())} | {out}")


if __name__ == "__main__":
    main()
