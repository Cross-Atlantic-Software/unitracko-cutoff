"""Run selected sources and write the aggregated Parquet output.

This is the bridge the frontend calls when you click "Generate": pick sources
(all or some), pick a mode (cached vs latest), get one normalized Parquet file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import cutoffs.adapters  # noqa: F401  (import populates the registry)
from cutoffs.deliverable import DELIVERABLE_CSV, write_deliverable
from cutoffs.enrich import enrich_frame
from cutoffs.registry import all_sources, get_source, source_names
from cutoffs.schema import empty_frame
from cutoffs.storage import DEFAULT_PATH, write_parquet

Mode = str  # "cached" | "latest"

# Sources excluded from the default "all" run (names=None). The bulk official-link
# scraper is breadth insurance that fires ~100 live requests, so it is opt-in only
# (pass include_optin=True or `--include-bulk`); this keeps the scheduled cron's
# default behaviour — the curated unified dataset — unchanged.
_OPTIN_SOURCES = {"bulk_official"}


def _meta_path(path: Path) -> Path:
    """Sidecar JSON next to the dataset recording when/how it was built."""
    return path.with_name("dataset_meta.json")


def _stamp(path: Path, *, mode: Mode, rows: int, sources: int,
           when: str | None = None) -> None:
    """Write the freshness sidecar so the UI can show 'data as of …'.

    ``when`` lets callers (e.g. CI) inject the timestamp; defaults to UTC now.
    """
    meta = {
        "generated_at": when or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "rows": int(rows),
        "sources": int(sources),
    }
    _meta_path(path).write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load_meta(path: str | Path = DEFAULT_PATH) -> dict:
    """Return the dataset freshness sidecar, or {} if it doesn't exist."""
    p = _meta_path(Path(path))
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def run(
    names: list[str] | None = None,
    mode: Mode = "cached",
    path: str | Path = DEFAULT_PATH,
    *,
    include_optin: bool = False,
    deliverable: bool = False,
) -> pd.DataFrame:
    """Generate the unified (Category-1) cutoff dataset.

    names: source names to include; None/empty => ALL registered sources except the
           opt-in breadth sources (see ``_OPTIN_SOURCES``).
    mode:  "cached" calls load_cached(); "latest" calls fetch_latest().
    include_optin: when names is None, also include the opt-in sources (e.g. the
           bulk official-link scraper).
    deliverable: also project the unified frame to the client's 14-column Category-1
           deliverable and write it to ``data/cat1_deliverable.csv``. Off by default
           so the UI "Generate" path only touches the internal Parquet.
    Returns the aggregated, normalized DataFrame (also written to ``path``).
    """
    if names:
        sources = [get_source(n) for n in names]
    else:
        sources = [s for s in all_sources()
                   if include_optin or s.meta.name not in _OPTIN_SOURCES]

    frames: list[pd.DataFrame] = []
    for src in sources:
        df = src.fetch_latest() if mode == "latest" else src.load_cached()
        frames.append(enrich_frame(src.normalize(df), src.meta))

    combined = (
        pd.concat(frames, ignore_index=True) if frames else empty_frame()
    )
    # Guard against duplicate rows leaking from overlapping sources/snapshots so
    # the unified dataset (and the deliverable projected from it) stays unique.
    combined = combined.drop_duplicates(ignore_index=True)
    path = Path(path)
    write_parquet(combined, path)
    _stamp(path, mode=mode, rows=len(combined), sources=len(sources))
    if deliverable:
        write_deliverable(combined)
    return combined


def available() -> list[str]:
    """List registered source names (for the frontend's selector)."""
    return source_names()


if __name__ == "__main__":  # pragma: no cover - CLI entry for the cron job
    import argparse

    parser = argparse.ArgumentParser(description="Build the cutoff dataset.")
    parser.add_argument("--mode", choices=["cached", "latest"], default="latest")
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    parser.add_argument("--category", choices=["1", "2", "3", "all"], default="1",
                        help="1=unified official dataset, 2=competitor raw tables, "
                             "3=cat-3 (no-link exams): fill a separate cat-1-shaped "
                             "table (data/cat3_cutoffs.csv) via Google/python where a "
                             "cutoff page is found, plus a provenance audit trail. "
                             "all=every pipeline")
    parser.add_argument("--include-bulk", action="store_true",
                        help="category 1: also run the bulk official-link scraper")
    args = parser.parse_args()

    import sys

    rc = 0  # accumulated exit code: non-zero if any stage fails

    if args.category in ("1", "all"):
        out = run(mode=args.mode, path=args.path, include_optin=args.include_bulk,
                  deliverable=True)
        print(f"[cat1] wrote {len(out):,} rows ({args.mode}) -> {args.path}")
        print(f"[cat1] wrote {len(out):,}-row 14-col deliverable -> {DELIVERABLE_CSV}")
    if args.category in ("2", "all"):
        from cutoffs.competitors.run import main as competitors_main
        rc |= competitors_main([])  # all competitors, every exam with a competitor link
        # Distil the freshly-scraped competitor tables into the labelled, lower-fidelity
        # aggregator deliverable (SEPARATE side table, never merged into the unified set).
        from cutoffs.aggregator import run_aggregator
        a = run_aggregator()
        print(f"[aggregator] wrote {a['rows']:,} rows across {a['exams']} exams "
              f"({a['colleges']} colleges) -> {a['path']}")
    if args.category in ("3", "all"):
        from cutoffs.cat3_provenance import run_cat3
        s = run_cat3()
        print(f"[cat3] wrote {s['cutoff_rows']:,} cat-1-shaped rows "
              f"({s['exams_with_rows']} exams) -> {s['cutoffs_path']}; "
              f"{s['provenance_rows']} provenance rows")

    sys.exit(rc)
