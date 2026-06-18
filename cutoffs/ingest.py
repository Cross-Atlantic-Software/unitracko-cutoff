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
from cutoffs.enrich import enrich_frame
from cutoffs.registry import all_sources, get_source, source_names
from cutoffs.schema import empty_frame
from cutoffs.storage import DEFAULT_PATH, write_parquet

Mode = str  # "cached" | "latest"


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
) -> pd.DataFrame:
    """Generate the dataset.

    names: source names to include; None/empty => ALL registered sources.
    mode:  "cached" calls load_cached(); "latest" calls fetch_latest().
    Returns the aggregated, normalized DataFrame (also written to ``path``).
    """
    if names:
        sources = [get_source(n) for n in names]
    else:
        sources = all_sources()

    frames: list[pd.DataFrame] = []
    for src in sources:
        df = src.fetch_latest() if mode == "latest" else src.load_cached()
        frames.append(enrich_frame(src.normalize(df), src.meta))

    combined = (
        pd.concat(frames, ignore_index=True) if frames else empty_frame()
    )
    path = Path(path)
    write_parquet(combined, path)
    _stamp(path, mode=mode, rows=len(combined), sources=len(sources))
    return combined


def available() -> list[str]:
    """List registered source names (for the frontend's selector)."""
    return source_names()


if __name__ == "__main__":  # pragma: no cover - CLI entry for the cron job
    import argparse

    parser = argparse.ArgumentParser(description="Build the cutoff dataset.")
    parser.add_argument("--mode", choices=["cached", "latest"], default="latest")
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    args = parser.parse_args()
    out = run(mode=args.mode, path=args.path)
    print(f"Wrote {len(out):,} rows ({args.mode}) -> {args.path}")
