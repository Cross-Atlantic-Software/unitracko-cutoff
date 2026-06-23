"""Orchestrate the Category-2 competitor scrape.

Reads the segmentation driver (``data/segmentation.csv``), and for each competitor
runs its scraper over every exam that carries that competitor's link, writing a
separate raw table ``data/competitor_<name>.parquet`` plus a freshness sidecar.
The four raw tables are NEVER merged into the unified official schema.

By default (``--category links``) it covers EVERY exam that carries a competitor
link — the client's Category 2, "all exams which have at least one competitor link"
— regardless of whether the exam also has a specific official link. Narrow with
``--category cat2`` (only exams with no official link) when you want the strictly
disjoint bucket.

    python -m cutoffs.competitors.run                       # all 4, every exam with that link
    python -m cutoffs.competitors.run --competitor collegedekho --limit 5
    python -m cutoffs.competitors.run --category cat2        # only the no-official-link bucket
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from cutoffs.competitors import _MODULE_NAMES, get_competitor, to_frame

ROOT = Path(__file__).resolve().parent.parent.parent
SEG_CSV = ROOT / "data" / "segmentation.csv"
OUT_DIR = ROOT / "data"

# None => no category filter (every exam with the link); the rest narrow to a bucket.
_CATEGORY_SETS = {"links": None, "cat2": {"cat2"}, "cat1": {"cat1"},
                  "all": {"cat1", "cat2"}}


def _load_segmentation(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _targets(seg_rows: list[dict[str, str]], competitor: str,
             categories: set[str] | None) -> list[tuple[str, str]]:
    """(exam, competitor_url) pairs in scope (the segmentation column == name).

    ``categories=None`` selects every exam that has this competitor link, regardless
    of segmentation category — the client's "all exams which have at least one
    competitor link". A set narrows to those buckets.
    """
    out = []
    for r in seg_rows:
        if categories is not None and r.get("category") not in categories:
            continue
        url = (r.get(competitor) or "").strip()
        if url:
            out.append((r.get("exam", ""), url))
    return out


def run_competitor(name: str, seg_rows: list[dict[str, str]], categories: set[str] | None,
                   *, limit: int | None = None, out_dir: Path = OUT_DIR,
                   when: str | None = None) -> dict:
    """Scrape one competitor over its in-scope exams; write parquet + sidecar."""
    mod = get_competitor(name)
    targets = _targets(seg_rows, name, categories)
    if limit:
        targets = targets[:limit]

    rows: list[dict] = []
    resolved = with_rows = 0
    for exam, url in targets:
        if mod.cutoff_urls(url, exam=exam):
            resolved += 1
        page_rows = mod.scrape(url, exam)
        if page_rows:
            with_rows += 1
            rows += page_rows

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    to_frame(rows).to_parquet(out_dir / f"competitor_{name}.parquet", index=False)

    stat = {
        "competitor": name,
        "generated_at": when or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "categories": "all-with-link" if categories is None else sorted(categories),
        "exams_attempted": len(targets),
        "exams_url_resolved": resolved,   # had a buildable cutoff URL (not a search link)
        "exams_with_rows": with_rows,
        "rows": len(rows),
    }
    (out_dir / f"competitor_{name}_meta.json").write_text(
        json.dumps(stat, indent=2), encoding="utf-8")
    return stat


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--competitor", choices=[*_MODULE_NAMES, "all"], default="all")
    parser.add_argument("--category", choices=list(_CATEGORY_SETS), default="links",
                        help="scope: 'links'=every exam with this competitor link "
                             "(default; the client's cat-2), 'cat2'=only no-official-link "
                             "exams, 'cat1', or 'all'")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap exams per competitor (for testing)")
    parser.add_argument("--segmentation", type=Path, default=SEG_CSV)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)

    if not args.segmentation.exists():
        print(f"segmentation CSV not found: {args.segmentation}\n"
              "Run: python scripts/segment_report.py", file=sys.stderr)
        return 1

    seg_rows = _load_segmentation(args.segmentation)
    categories = _CATEGORY_SETS[args.category]
    names = _MODULE_NAMES if args.competitor == "all" else [args.competitor]
    for name in names:
        s = run_competitor(name, seg_rows, categories, limit=args.limit,
                           out_dir=args.out_dir)
        print(f"{name:14s} attempted={s['exams_attempted']:4d} "
              f"url_resolved={s['exams_url_resolved']:4d} "
              f"with_rows={s['exams_with_rows']:4d} rows={s['rows']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
