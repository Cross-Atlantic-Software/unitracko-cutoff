"""Distil the Cat-3 web-research batches into a clearly-labelled side table.

Phase-7 Cat-3 ("no automatable link") fallback: for every catalogued exam that
plausibly has cutoffs but that neither the official-link path nor the competitor
aggregator could reach, a pool of web-research agents searched the open web for the
exam's *actual* cutoff page and extracted rows into
``data/cat3_web/results/batch_*.json``.

This module folds those per-batch JSON files into a single deliverable-shaped CSV
(``data/cat3_web_cutoffs.csv``) with the same 15 columns as the competitor
aggregator (the 14-col client deliverable + ``Category``). Like the aggregator and
``mp_aggregator``, it is a SEPARATE, lower-fidelity side table — it is NEVER merged
into ``data/cutoffs.parquet`` (the official unified schema).

Run: ``python -m cutoffs.cat3_web``
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "data" / "cat3_web" / "results"
# Second pass (official-link search) that also extracted some rows from official PDFs.
LINKS_RESULTS_DIR = ROOT / "data" / "cat3_web" / "links_results"
# Adversarial QA verdicts: per-exam fidelity tier + drop flag (see verify_results/).
FIDELITY_JSON = ROOT / "data" / "cat3_web" / "fidelity.json"
OUT_CSV = ROOT / "data" / "cat3_web_cutoffs.csv"

# The deliverable 14 columns + Category + a fidelity note, in client order.
COLUMNS = [
    "Exam Name", "Link of website", "College Name", "City", "State", "Program",
    "Branch", "Year - cutoff", "Round #", "Gender", "Quota", "Category",
    "Opening Rank", "Closing Rank", "Cutoff Percentile/Score",
    "Link - Data Taken from", "Fidelity",
]


def load_fidelity(path: Path = FIDELITY_JSON) -> dict[str, dict]:
    """Per-exam QA verdict: ``{exam: {fidelity, drop, note}}``. Empty if absent."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}

# Row-level fields the agents emit (super-set of COLUMNS minus Exam Name/website).
_ROW_FIELDS = [
    "College Name", "City", "State", "Program", "Branch", "Year - cutoff",
    "Round #", "Gender", "Quota", "Category", "Opening Rank", "Closing Rank",
    "Cutoff Percentile/Score", "Link - Data Taken from",
]


def _coerce_rank(value: object) -> object:
    """Best-effort int for a rank cell; keep None/blank as None, leave non-numeric."""
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if not s or s.lower() in {"-", "na", "n/a", "nan", "none", "null", "tba", "--"}:
        return None
    try:
        return int(round(float(s)))
    except (ValueError, OverflowError):
        return None


def _has_signal(row: dict) -> bool:
    """Keep only rows that carry a real cutoff signal (a rank or a percentile/score)."""
    return any(row.get(k) not in (None, "", "null")
               for k in ("Opening Rank", "Closing Rank", "Cutoff Percentile/Score"))


def load_results(results_dir=RESULTS_DIR,
                 websites: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    """Read every ``batch_*.json``; return (deliverable rows, per-exam status map).

    ``results_dir`` may be a single directory or an iterable of directories (the
    first-pass extraction plus the official-link second pass, which also pulled rows
    from a few official PDFs). ``websites`` maps exam -> official site; each row's
    "Link of website" is set to it so the cutoff is connected to the AUTHORITATIVE
    source, while the page the data was actually scraped from stays in
    "Link - Data Taken from".
    """
    if websites is None:
        from cutoffs.segmentation import official_website_map
        websites = official_website_map()
    fidelity = load_fidelity()
    dirs = [results_dir] if isinstance(results_dir, (str, Path)) else list(results_dir)
    rows: list[dict] = []
    status: dict[str, dict] = {}
    for d in dirs:
        for path in sorted(Path(d).glob("batch_*.json")):
            try:
                blob = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            for exam, info in blob.items():
                if not isinstance(info, dict):
                    continue
                verdict = fidelity.get(exam, {})
                if verdict.get("drop"):
                    continue  # adversarial QA flagged this exam's rows as unreliable
                tier = verdict.get("fidelity")
                kept = 0
                for raw in info.get("rows") or []:
                    row = {c: raw.get(c) for c in _ROW_FIELDS}
                    row["Opening Rank"] = _coerce_rank(row.get("Opening Rank"))
                    row["Closing Rank"] = _coerce_rank(row.get("Closing Rank"))
                    if not _has_signal(row):
                        continue
                    # If the agent didn't capture a per-row source, fall back to the
                    # exam's overall source page so provenance is never lost.
                    if not row.get("Link - Data Taken from"):
                        row["Link - Data Taken from"] = info.get("source_url")
                    row["Exam Name"] = exam
                    # Connect to the official site; provenance stays in "Link - Data Taken from".
                    row["Link of website"] = websites.get(exam) or info.get("source_url")
                    row["Fidelity"] = tier
                    rows.append(row)
                    kept += 1
                prior = status.get(exam, {"rows_kept": 0})
                status[exam] = {
                    "status": info.get("status") or info.get("data_status"),
                    "note": info.get("note") or info.get("official_note"),
                    "rows_kept": prior["rows_kept"] + kept,
                }
    return rows, status


def build(results_dir=(RESULTS_DIR, LINKS_RESULTS_DIR),
          out_csv: Path = OUT_CSV) -> pd.DataFrame:
    """Aggregate the batches into the deliverable side table and write it to CSV."""
    rows, status = load_results(results_dir)
    df = pd.DataFrame(rows, columns=COLUMNS)
    if not df.empty:
        df = df.drop_duplicates(ignore_index=True)
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    ok = sum(1 for s in status.values() if s["rows_kept"] > 0)
    print(f"cat3_web: {len(df):,} rows across {df['Exam Name'].nunique()} exams "
          f"(of {len(status)} researched; {ok} yielded rows) -> {out_csv}")
    return df


if __name__ == "__main__":
    build()
