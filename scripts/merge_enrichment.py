"""Fold the enrichment-workflow output into data/catalog.parquet.

Usage:
    python scripts/merge_enrichment.py path/to/workflow_result.json

The JSON may be either the raw ``{"records": [...]}`` object or a list of
records. Joins on the verbatim exam name (see cutoffs.catalog.merge_enrichment).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from cutoffs.catalog import merge_enrichment


def _load_records(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        # accept {"records": [...]} or {"result": {"records": [...]}}
        if "records" in raw:
            return raw["records"]
        if isinstance(raw.get("result"), dict):
            return raw["result"].get("records", [])
    return raw if isinstance(raw, list) else []


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    records = _load_records(Path(argv[1]))
    cat = merge_enrichment(records)
    filled = (cat["Body"].astype(str).str.strip() != "").sum()
    metrics = (cat["Metric"].astype(str).str.strip() != "").sum()
    print(f"Merged {len(records)} records -> {len(cat)} catalog rows.")
    print(f"Body filled: {filled}/{len(cat)} | Metric filled: {metrics}/{len(cat)}")
    print("\nMetric distribution:")
    print(cat["Metric"].replace("", "(none)").value_counts().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
