"""Category-1 scrapeability report — what the official-link scraper can realistically reach.

Joins the Category-1 exams (from segmentation) to their probe bucket and the
dispatch decision, then prints how many official links are live-scrapeable HTML /
JS / PDF versus dead (404/403/5xx/error/no-url -> Category-3 provenance). Pure
standard library; runs anywhere. This makes the "reality check" concrete before
any network code runs.

    python scripts/bulk_report.py
"""
from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(mod_name: str, rel_path: str):
    """Load a cutoffs submodule straight from its file (no pandas-pulling __init__)."""
    try:
        return __import__(f"cutoffs.{mod_name}", fromlist=[mod_name])
    except ModuleNotFoundError:
        spec = importlib.util.spec_from_file_location(f"cutoffs_{mod_name}", ROOT / rel_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod


seg = _load("segmentation", "cutoffs/segmentation.py")
dispatch = _load("dispatch", "cutoffs/dispatch.py")


def main() -> int:
    buckets = dispatch.load_probe_buckets()
    cat1 = [r for r in seg.segment() if r.category == "cat1"]

    by_fetcher: Counter[str] = Counter()
    by_bucket: Counter[str] = Counter()
    for r in cat1:
        bucket = buckets.get((r.official_cutoff_url or "").strip(), "")
        by_bucket[bucket or "(no probe match)"] += 1
        by_fetcher[dispatch.fetcher_name(bucket)] += 1

    live = by_fetcher["html"] + by_fetcher["js"] + by_fetcher["pdf"]
    print(f"Category-1 official links: {len(cat1)}\n")
    print("By fetcher (what we will attempt):")
    for key in ("html", "js", "pdf", "none"):
        label = {"html": "HTML scraper", "js": "JS render (Playwright)",
                 "pdf": "PDF parse", "none": "DEAD -> cat3 provenance"}[key]
        print(f"  {label:28s} {by_fetcher[key]:4d}")
    print(f"\n  live-scrapeable attempts    : {live}")
    print(f"  dead (routed to cat3)       : {by_fetcher['none']}")
    print("\nBy probe bucket:")
    for bucket, n in by_bucket.most_common():
        print(f"  {bucket:22s} {n:4d}  -> {dispatch.fetcher_name(bucket)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
