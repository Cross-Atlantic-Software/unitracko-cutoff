"""Tests for the MP aggregator collector (pure given an injected extractor)."""
from __future__ import annotations

from cutoffs.deliverable import deliverable_columns
from cutoffs.mp_aggregator import collect

_FOURTEEN = [label for _, label in deliverable_columns()]


def _stub_extract(url):
    return [
        {"institute_name": "Jabalpur Engineering College", "branch_or_course": "CSE",
         "category": "UR", "closing_rank": 12345, "opening_rank": 1000},
        # duplicate of the above (must be deduped):
        {"institute_name": "Jabalpur Engineering College", "branch_or_course": "CSE",
         "category": "UR", "closing_rank": 12345},
        # missing institute -> dropped:
        {"institute_name": "", "branch_or_course": "ECE", "closing_rank": 999},
    ]


def test_collect_projects_to_14_columns_and_dedups():
    rows = collect(extract_fn=_stub_extract, year=2024)
    assert len(rows) == 1                       # dup dropped, blank-institute dropped
    row = rows[0]
    assert list(row.keys()) == _FOURTEEN        # exactly the client's 14 columns
    assert row["Exam Name"] == "MP DTE"
    assert row["State"] == "Madhya Pradesh"
    assert row["College Name"] == "Jabalpur Engineering College"
    assert row["Closing Rank"] == 12345
    assert row["Link - Data Taken from"].startswith("http")


def test_collect_empty_when_nothing_extracted():
    assert collect(extract_fn=lambda url: [], year=2024) == []
