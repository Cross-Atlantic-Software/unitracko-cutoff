"""Tests for the Phase-6 exam segmentation (cat1 / cat2 / cat3).

Pure standard library — no pandas/network — so the partition is locked against the
real committed sheets. Two layers: data-driven assertions on the actual
cutoffexamsheet/examlinkssheet (exact counts), and synthetic-sheet tests that pin
the classification invariants independent of the data.
"""
from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from cutoffs.segmentation import (
    CAT1_STATUS_FULL,
    JEE_SPLIT,
    counts,
    flag_summary,
    load_sheets,
    segment,
    write_segmentation,
)


# --------------------------------------------------------------------------
# Data-driven: exact counts on the real committed sheets.
# --------------------------------------------------------------------------
def test_default_counts():
    """Default (merit lists count, strict exact-name join) -> 203 / 102 / 16."""
    assert counts(segment()) == {"cat1": 203, "cat2": 102, "cat3": 16, "total": 321}


def test_jee_remap_lifts_five_into_cat1():
    rows = segment(jee_remap=True)
    assert counts(rows) == {"cat1": 208, "cat2": 102, "cat3": 11, "total": 321}
    assert flag_summary(rows)["jee_remapped"] == len(JEE_SPLIT) == 5


def test_excluding_merit_lists_shrinks_cat1():
    """Without merit lists, cat1 drops to the hard-cutoff rows only (139)."""
    nm = counts(segment(merit_list=False))
    assert nm["cat1"] == 139
    assert nm["cat1"] < counts(segment())["cat1"]
    assert nm["total"] == 321


def test_review_flag_counts():
    flags = flag_summary(segment())
    assert flags["aggregator_as_official"] == 19
    assert flags["prose_cutoff_url"] == 15
    assert flags["prose_homepage"] == 13


def test_categories_are_exhaustive_and_exclusive():
    rows = segment()
    cats = {r.category for r in rows}
    assert cats <= {"cat1", "cat2", "cat3"}
    c = counts(rows)
    assert c["cat1"] + c["cat2"] + c["cat3"] == c["total"] == len(rows)


def test_cat1_is_exactly_the_specific_status_rows():
    """Every cat1 row carries a CAT1 status; no CAT1-status row leaks to cat2/cat3."""
    for r in segment():
        if r.cutoff_status in CAT1_STATUS_FULL:
            assert r.category == "cat1"
        if r.category == "cat1":
            assert r.cutoff_status in CAT1_STATUS_FULL


def test_cat2_rows_have_a_competitor_link_and_no_cat1_status():
    for r in segment():
        if r.category == "cat2":
            assert r.n_competitor_links > 0
            assert r.cutoff_status not in CAT1_STATUS_FULL


def test_cat3_rows_have_no_links_under_strict_join():
    for r in segment():
        if r.category == "cat3":
            assert r.n_competitor_links == 0
            assert r.cutoff_status not in CAT1_STATUS_FULL


def test_aggregator_flag_only_on_cat1():
    assert all(r.category == "cat1" for r in segment() if r.aggregator_as_official)


def test_real_sheets_join_cleanly():
    cut_rows, links = load_sheets()
    assert len(cut_rows) == 321
    matched = sum(1 for r in cut_rows if r["Exam"].strip() in links)
    assert matched == 316  # 5 JEE-split rows are unmatched under a strict join


# --------------------------------------------------------------------------
# Synthetic: pin the priority order and rules independent of the real data.
# --------------------------------------------------------------------------
def _write(dir_: Path, name: str, header: list[str], rows: list[list[str]]) -> Path:
    path = dir_ / name
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return path


def test_priority_order_cat1_beats_cat2():
    """An Official-Cutoff exam that ALSO has a competitor link must resolve cat1."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        cut = _write(d, "cut.csv", ["Exam", "Homepage", "CutoffURL"], [
            ["A Has Both", "https://a.gov.in", "https://a.gov.in/cutoff"],
            ["B Competitor Only", "https://b.gov.in", "https://b.gov.in"],
            ["C No Links", "https://c.gov.in", "https://c.gov.in"],
        ])
        links = _write(d, "links.csv",
                       ["Exam", "CutoffStatus", "CollegeDunia", "Shiksha", "Careers360", "CollegeDekho"], [
                           ["A Has Both", "Official Cutoff", "https://collegedunia.com/x", "", "", ""],
                           ["B Competitor Only", "No Cutoff Exists", "https://collegedunia.com/y", "", "", ""],
                           ["C No Links", "No Cutoff Exists", "", "", "", ""],
                       ])
        by_exam = {r.exam: r for r in segment(cut_path=cut, links_path=links)}
        assert by_exam["A Has Both"].category == "cat1"          # cat1 wins over competitor link
        assert by_exam["A Has Both"].n_competitor_links == 1
        assert by_exam["B Competitor Only"].category == "cat2"
        assert by_exam["C No Links"].category == "cat3"


def test_unmatched_exam_falls_to_cat3():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        cut = _write(d, "cut.csv", ["Exam", "Homepage", "CutoffURL"],
                     [["Orphan Exam", "https://o.gov.in", "https://o.gov.in/c"]])
        links = _write(d, "links.csv",
                       ["Exam", "CutoffStatus", "CollegeDunia", "Shiksha", "Careers360", "CollegeDekho"],
                       [["Different Exam", "Official Cutoff", "", "", "", ""]])
        rows = segment(cut_path=cut, links_path=links)
        assert rows[0].category == "cat3"


def test_prose_and_aggregator_flags():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        cut = _write(d, "cut.csv", ["Exam", "Homepage", "CutoffURL"], [
            ["Agg Official", "https://x.gov.in", "https://www.shiksha.com/foo"],
            ["Prose Links", "State counselling portals", "Use the respective state portal"],
        ])
        links = _write(d, "links.csv",
                       ["Exam", "CutoffStatus", "CollegeDunia", "Shiksha", "Careers360", "CollegeDekho"], [
                           ["Agg Official", "Official Cutoff", "", "", "", ""],
                           ["Prose Links", "Official Cutoff", "", "", "", ""],
                       ])
        by_exam = {r.exam: r for r in segment(cut_path=cut, links_path=links)}
        assert by_exam["Agg Official"].aggregator_as_official is True
        assert by_exam["Prose Links"].prose_cutoff_url is True
        assert by_exam["Prose Links"].prose_homepage is True


def test_write_segmentation_roundtrip():
    rows = segment()
    with tempfile.TemporaryDirectory() as d:
        out = write_segmentation(rows, Path(d) / "seg.csv")
        with open(out, encoding="utf-8") as fh:
            reread = list(csv.DictReader(fh))
        assert len(reread) == len(rows)
        assert reread[0]["category"] in {"cat1", "cat2", "cat3"}
        assert {"exam", "category", "official_cutoff_url"} <= set(reread[0])
