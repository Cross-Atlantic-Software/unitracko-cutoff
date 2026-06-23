"""Tests for the aggregator distiller — the pure row-level logic (no parquet/net)."""
from __future__ import annotations

import json

from cutoffs.aggregator import (
    _category_from_raw,
    _clean,
    _is_caption,
    _numeric,
    _rank_from_raw,
    _row_signal,
    _year_from,
)


def test_numeric_parses_messy_cells_and_rejects_noise():
    assert _numeric("1,234") == 1234
    assert _numeric("1234 (Gen)") == 1234
    assert _numeric("Will be notified") is None
    assert _numeric("--") is None
    assert _numeric(None) is None
    assert _numeric(987) == 987


def test_clean_coerces_nan_and_none_strings():
    assert _clean(float("nan")) == ""
    assert _clean("nan") == ""
    assert _clean("  AMU  ") == "AMU"
    assert _clean(None) == ""


def test_rank_from_raw_recovers_opening_and_closing():
    raw = json.dumps({"Opening Rank": "1,000", "Closing Rank": "12,345"})
    assert _rank_from_raw(raw) == (1000, 12345)
    # a category->cutoff grid (only a closing-style key):
    assert _rank_from_raw(json.dumps({"Category": "SC", "Cut off": "1480"}))[1] == 1480
    assert _rank_from_raw("not json") == (None, None)


def test_category_recovered_from_raw_cells():
    raw = json.dumps({"Category": "OBC", "Cut off": "330"})
    assert _category_from_raw(raw) == "OBC"
    # a numeric value under a category-ish key is not a category:
    assert _category_from_raw(json.dumps({"Category": "123"})) is None


def test_year_from_caption_when_column_missing():
    assert _year_from({"table_caption": "AILET 2026 Round 1 Cut-Off"}) == 2026
    assert _year_from({"year": 2024}) == 2024
    assert _year_from({"table_caption": "no year here"}) is None


def test_row_signal_keeps_real_cutoff_drops_noise():
    # a genuine college x branch x rank row survives:
    good = _row_signal({
        "exam": "KCET", "institute_name": "RV College", "branch_or_course": "CSE",
        "closing_rank": "1500", "year": 2024,
    })
    assert good is not None
    assert good["Institute"] == "RV College"
    assert good["ClosingRank"] == 1500
    assert good["Exam"] == "KCET"

    # a placeholder/calendar row with no rank anywhere is dropped:
    assert _row_signal({
        "exam": "ACET", "institute_name": "June 2026",
        "raw_cells": json.dumps({"Events": "Form starts", "Dates": "Feb 10"}),
    }) is None

    # category-grid row with no institute but a category+rank survives:
    grid = _row_signal({
        "exam": "AILET", "institute_name": "",
        "raw_cells": json.dumps({"Category": "SC", "Cut off": "1480"}),
    })
    assert grid is not None
    assert grid["Category"] == "SC"
    assert grid["ClosingRank"] == 1480


def test_is_caption_distinguishes_captions_from_colleges():
    assert _is_caption("AILET 2026 Round 1 BA LLB Cut-Off")
    assert _is_caption("AMU BA LLB Cut-Off 2024 Details")
    assert not _is_caption("Amrita School of Engineering, Coimbatore")
    assert not _is_caption("RV College of Engineering")


def test_caption_college_is_blanked_not_passed_off_as_a_college():
    # caption-as-college WITH a category -> survives as an exam-level grid, no college:
    row = _row_signal({
        "exam": "AILET", "institute_name": "AILET 2026 Round 1 BA LLB Cut-Off",
        "raw_cells": json.dumps({"Category": "OBC", "Cut off": "330"}),
    })
    assert row is not None
    assert row["Institute"] == ""          # caption blanked, not shipped as a college
    assert row["Category"] == "OBC"
    # caption-as-college with NO category but a real rank -> kept as a lower-resolution
    # exam-level cutoff (college blanked), so the exam isn't lost from coverage:
    bare = _row_signal({
        "exam": "AILET", "institute_name": "AILET 2026 Cut-Off", "closing_rank": "330",
    })
    assert bare is not None
    assert bare["Institute"] == ""
    assert bare["ClosingRank"] == 330
    # a true non-cutoff row (no rank anywhere) is still dropped:
    assert _row_signal({"exam": "AILET", "institute_name": "AILET 2026 Cut-Off"}) is None


def test_inverted_open_close_ranks_are_swapped():
    row = _row_signal({
        "exam": "X", "institute_name": "Some College",
        "opening_rank": "5000", "closing_rank": "1000",
    })
    assert row["OpeningRank"] == 1000      # the better (lower) rank
    assert row["ClosingRank"] == 5000


def test_row_signal_falls_back_to_percentile_for_closing():
    row = _row_signal({
        "exam": "X", "institute_name": "Some College",
        "cutoff_percentile": "98",
    })
    assert row["ClosingRank"] == 98


def test_score_fallback_not_mixed_with_an_opening_rank():
    # opening RANK present but closing rank absent, with a marks/score value: the
    # score must NOT become ClosingRank (different unit -> false opening>closing).
    row = _row_signal({
        "exam": "BHU", "institute_name": "Some College",
        "opening_rank": "64", "cutoff_score_or_marks": "49",
    })
    assert row["OpeningRank"] == 64
    assert row["ClosingRank"] is None      # not 49 (that's marks, not a rank)
