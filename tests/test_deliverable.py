"""Tests for the 14-column Category-1 deliverable projection (pure stdlib)."""
from __future__ import annotations

from cutoffs.deliverable import (
    DELIVERABLE_COLUMNS,
    deliverable_columns,
    deliverable_rename,
    project_records,
)

# The client's exact 14 labels, in order.
_CLIENT_LABELS = [
    "Exam Name", "Link of website", "College Name", "City", "State", "Program",
    "Branch", "Year - cutoff", "Round #", "Gender", "Quota", "Opening Rank",
    "Closing Rank", "Link - Data Taken from",
]


def test_fourteen_columns_in_client_order():
    labels = [label for _, label in DELIVERABLE_COLUMNS]
    assert labels == _CLIENT_LABELS
    assert len(DELIVERABLE_COLUMNS) == 14


def test_college_maps_from_institute_and_source_from_sourceurl():
    rename = deliverable_rename()
    assert rename["Institute"] == "College Name"
    assert rename["SourceURL"] == "Link - Data Taken from"
    assert rename["Year"] == "Year - cutoff"
    # Body / Level / Category / CategoryGroup are intentionally absent.
    for dropped in ("Body", "Level", "Category", "CategoryGroup"):
        assert dropped not in rename


def test_project_records_selects_and_renames():
    row = {
        "Body": "JoSAA", "Exam": "JEE Advanced", "Website": "https://x",
        "Institute": "IIT Bombay", "City": "Mumbai", "State": "All India",
        "Program": "B.Tech", "Branch": "CSE", "Year": 2024, "Round": "1",
        "Gender": "Gender-Neutral", "Quota": "AI", "OpeningRank": 1,
        "ClosingRank": 66, "SourceURL": "https://x/cutoff", "Category": "OPEN",
    }
    out = project_records([row])[0]
    assert list(out.keys()) == _CLIENT_LABELS
    assert out["Exam Name"] == "JEE Advanced"
    assert out["College Name"] == "IIT Bombay"
    assert out["Link - Data Taken from"] == "https://x/cutoff"
    assert "Body" not in out and "Category" not in out


def test_missing_source_key_becomes_none():
    out = project_records([{"Exam": "X"}])[0]
    assert out["Exam Name"] == "X"
    assert out["Closing Rank"] is None


def test_include_category_inserts_after_quota():
    cols = deliverable_columns(include_category=True)
    labels = [label for _, label in cols]
    assert len(cols) == 15
    assert labels[labels.index("Quota") + 1] == "Category"
    out = project_records([{"Category": "OBC-NCL"}], include_category=True)[0]
    assert out["Category"] == "OBC-NCL"
