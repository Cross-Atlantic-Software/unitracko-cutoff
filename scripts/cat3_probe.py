"""Run the Category-3 pass for the "no link at all" exams.

Client rule: cat-3 = exams with neither a specific cutoff link nor a competitor
link; for these, "check on google/python script — if able to fill the table as
first one (just make another table - so we know)". So a found cutoff page yields a
SEPARATE table shaped like the cat-1 14-column deliverable.

This pass searches (Google/DuckDuckGo) for each exam, and where a cutoff-like page
is found, extracts its rows into ``data/cat3_cutoffs.csv`` (the 14 deliverable
columns). It also writes a ``data/cat3_provenance.parquet`` audit trail (one row per
exam attempted — query, candidate URL, whether a table was found, rows extracted).

    python scripts/cat3_probe.py                 # all cat-3 exams
    python scripts/cat3_probe.py --limit 5       # first 5 (testing)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cutoffs import cat3_provenance as cp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--out-cutoffs", type=Path, default=cp.CAT3_CUTOFFS_CSV)
    parser.add_argument("--out-provenance", type=Path, default=cp.PROVENANCE_PATH)
    parser.add_argument("--segmentation", type=Path, default=cp.SEG_CSV)
    args = parser.parse_args(argv)

    exams = cp.cat3_exams(args.segmentation)
    if args.limit is not None:
        exams = exams[: max(0, args.limit)]
    if not exams:
        print("No cat-3 exams found. Run: python scripts/segment_report.py", file=sys.stderr)
        return 1

    s = cp.run_cat3(exams, out_cutoffs=args.out_cutoffs,
                    out_provenance=args.out_provenance, year=args.year)
    print(f"Probed {s['exams']} cat-3 exams")
    print(f"  candidate cutoff page found : {s['found_pages']}")
    print(f"  exams with extracted rows   : {s['exams_with_rows']}")
    print(f"  cat-1-shaped rows written   : {s['cutoff_rows']} -> {s['cutoffs_path']}")
    print(f"  provenance audit trail      : {s['provenance_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
