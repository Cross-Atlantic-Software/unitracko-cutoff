"""Write the Phase-6 segmentation driver CSV and print a summary.

Produces ``data/segmentation.csv`` — the single source of truth every downstream
pipeline reads (cat-1 official dispatch, cat-2 competitor scraping over every exam
with a competitor link, and the cat-3 pass — which fills a separate table shaped
like the cat-1 14-column deliverable where Google / a python script recovers a
cutoff page). Pure standard library, so it runs in the most minimal environment.

    python scripts/segment_report.py                 # default: merit lists count, strict join
    python scripts/segment_report.py --jee-remap     # fold the 5 JEE variants into cat-1
    python scripts/segment_report.py --no-merit-list # require a hard cutoff (exclude merit lists)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Prefer the normal package import; fall back to loading the module straight from
# its file when pandas (a heavy optional dep pulled in by ``cutoffs/__init__``) is
# absent — segmentation itself needs nothing but the standard library.
try:
    from cutoffs import segmentation as seg
except ModuleNotFoundError:
    import importlib.util

    _path = Path(__file__).resolve().parent.parent / "cutoffs" / "segmentation.py"
    _spec = importlib.util.spec_from_file_location("cutoffs_segmentation", _path)
    seg = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = seg  # @dataclass resolves types via sys.modules
    _spec.loader.exec_module(seg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jee-remap", action="store_true",
                        help="map the 5 JEE-split exams onto the collapsed links row (-> cat1)")
    parser.add_argument("--no-merit-list", action="store_true",
                        help="exclude 'Official Merit List' from cat1 (hard cutoff only)")
    parser.add_argument("--out", type=Path, default=seg.SEGMENTATION_CSV,
                        help="output CSV path (default: data/segmentation.csv)")
    args = parser.parse_args(argv)

    rows = seg.segment(merit_list=not args.no_merit_list, jee_remap=args.jee_remap)
    out = seg.write_segmentation(rows, args.out)

    c = seg.counts(rows)
    flags = seg.flag_summary(rows)
    print(f"Wrote {len(rows)} exams -> {out}")
    print(f"  cat1 (specific official link) : {c['cat1']}")
    print(f"  cat2 (>=1 competitor link)    : {c['cat2']}")
    print(f"  cat3 (no link at all)         : {c['cat3']}")
    print("\nReview flags:")
    print(f"  aggregator-as-official (cat1) : {flags['aggregator_as_official']}")
    print(f"  prose CutoffURL (not a link)  : {flags['prose_cutoff_url']}")
    print(f"  prose Homepage (not a link)   : {flags['prose_homepage']}")
    if args.jee_remap:
        print(f"  JEE rows remapped to cat1     : {flags['jee_remapped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
