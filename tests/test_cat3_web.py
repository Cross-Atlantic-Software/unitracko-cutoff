"""Tests for the Cat-3 web-research side-table builder (pure file -> CSV)."""
from __future__ import annotations

import json

from cutoffs.cat3_web import COLUMNS, build, load_results


def _write_batch(results_dir, name, payload):
    (results_dir / name).write_text(json.dumps(payload), encoding="utf-8")


def test_load_results_keeps_only_signal_rows(tmp_path):
    rd = tmp_path / "results"
    rd.mkdir()
    _write_batch(rd, "batch_00.json", {
        "Exam A": {
            "status": "ok", "source_url": "https://a.example/cutoff", "note": "x",
            "rows": [
                # real closing rank -> kept (and coerced from "1,234")
                {"College Name": "C1", "Branch": "CSE", "Category": "OBC",
                 "Closing Rank": "1,234", "Link - Data Taken from": "https://a.example/p1"},
                # percentile only, no rank -> kept
                {"College Name": "C2", "Branch": "ECE", "Category": "GEN",
                 "Cutoff Percentile/Score": "92.5", "Closing Rank": None,
                 "Link - Data Taken from": "https://a.example/p2"},
                # no signal at all -> dropped
                {"College Name": "C3", "Branch": "ME", "Category": "SC",
                 "Link - Data Taken from": "https://a.example/p3"},
            ],
        },
        "Exam B": {"status": "none", "source_url": "", "note": "merit list", "rows": []},
    })

    # Inject the official-website map: the cutoff data (from a third-party page)
    # must be connected to the AUTHORITATIVE site, with provenance kept separate.
    rows, status = load_results(rd, websites={"Exam A": "https://official.example"})
    assert len(rows) == 2                          # the no-signal row was dropped
    kept = next(r for r in rows if r["College Name"] == "C1")
    assert kept["Closing Rank"] == 1234            # comma-coerced to int
    assert kept["Exam Name"] == "Exam A"
    assert kept["Link of website"] == "https://official.example"   # official site
    assert kept["Link - Data Taken from"] == "https://a.example/p1"  # provenance kept
    assert status["Exam A"]["rows_kept"] == 2
    assert status["Exam B"]["rows_kept"] == 0      # honest empty is recorded


def test_unmapped_exam_falls_back_to_source_url(tmp_path):
    rd = tmp_path / "results"
    rd.mkdir()
    _write_batch(rd, "batch_00.json", {
        "Exam X": {"status": "ok", "source_url": "https://src.example/page", "note": "",
                   "rows": [{"College Name": "C", "Closing Rank": 7,
                             "Link - Data Taken from": "https://src.example/page"}]},
    })
    rows, _ = load_results(rd, websites={})         # no official site known
    assert rows[0]["Link of website"] == "https://src.example/page"  # graceful fallback


def test_build_writes_deliverable_shaped_csv(tmp_path):
    rd = tmp_path / "results"
    rd.mkdir()
    _write_batch(rd, "batch_00.json", {
        "Exam A": {"status": "ok", "source_url": "https://a.example", "note": "",
                   "rows": [{"College Name": "C1", "Closing Rank": 5,
                             "Link - Data Taken from": "https://a.example/p"}]},
    })
    out = tmp_path / "cat3_web_cutoffs.csv"
    df = build(results_dir=rd, out_csv=out)
    assert out.exists()
    assert list(df.columns) == COLUMNS             # exact deliverable shape
    assert len(df) == 1
