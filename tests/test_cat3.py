"""Tests for the Category-3 provenance pass (pure-stdlib surface).

The search/fetch functions are injected as stubs, so the attempt/record logic is
exercised without a network.
"""
from __future__ import annotations

from cutoffs.cat3_provenance import (
    CAT3_PROVENANCE_COLUMNS,
    PROVENANCE_COLUMNS,
    _exam_from_query,
    _is_relevant,
    _rank_urls,
    _raw_to_unified,
    _relax_query,
    attempt,
    build_query,
    build_records,
    count_tables,
    fill_cat3,
    looks_like_cutoff,
)
from cutoffs.deliverable import DELIVERABLE_COLUMNS

# The 18 unified-schema column names (inlined to avoid importing pandas-backed schema).
_UNIFIED_SCHEMA = {
    "Body", "Exam", "Website", "Level", "State", "City", "Institute", "Program",
    "Branch", "Category", "CategoryGroup", "Quota", "Gender", "Year", "Round",
    "OpeningRank", "ClosingRank", "SourceURL",
}


def test_build_query():
    q = build_query("Some Exam", year=2025)
    assert '"Some Exam"' in q
    assert "cutoff" in q and "merit list" in q.lower() and "2025" in q


def test_count_tables_and_looks_like_cutoff():
    assert count_tables("<TABLE></table><table></table>") == 2
    assert looks_like_cutoff("<table>Closing Rank by category</table>") is True
    # a table with no cutoff wording, or wording with no table -> False
    assert looks_like_cutoff("<table>random content</table>") is False
    assert looks_like_cutoff("closing rank but no table here") is False


def test_attempt_found():
    rec = attempt(
        "Exam X", year=None,
        search_fn=lambda q: ["https://site.edu/cutoff"],
        fetch_fn=lambda u: (True, 3, True),
    )
    assert rec.candidate_url == "https://site.edu/cutoff"
    assert rec.found is True and rec.http_ok is True and rec.n_tables == 3
    assert "found" in rec.note


def test_attempt_no_result():
    rec = attempt("Exam Y", year=None, search_fn=lambda q: [], fetch_fn=lambda u: (True, 1, True))
    assert rec.candidate_url == "" and rec.found is False
    assert rec.note == "no search result"


def test_attempt_fetched_but_no_cutoff():
    rec = attempt("Exam Z", year=None,
                  search_fn=lambda q: ["https://x.org"], fetch_fn=lambda u: (True, 0, False))
    assert rec.found is False and rec.http_ok is True
    assert "no cutoff table" in rec.note


def test_build_records_shape():
    recs = build_records(
        ["A", "B"], year=2024, when="2026-01-01T00:00:00+00:00",
        search_fn=lambda q: ["https://u/cutoff"],
        fetch_fn=lambda u: (True, 2, True),
    )
    assert len(recs) == 2
    assert set(recs[0]) == set(PROVENANCE_COLUMNS)
    assert recs[0]["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert recs[0]["found"] is True


# --------------------------------------------------------------------------
# fill_cat3 — the cat-1-shaped backfill ("make another table so we know").
# --------------------------------------------------------------------------
_FOURTEEN = [label for _, label in DELIVERABLE_COLUMNS]


def test_fill_cat3_extracts_and_projects_to_14_columns():
    prov, deliverable = fill_cat3(
        ["Exam X"], year=None, when="T",
        search_fn=lambda q: ["https://site.edu/cutoff"],
        fetch_fn=lambda u: (True, 2, True),
        extract_fn=lambda e, u: [{"Institute": "IIT Z", "Branch": "CSE",
                                  "OpeningRank": 1, "ClosingRank": 66}],
    )
    assert prov[0]["found"] is True and prov[0]["rows_extracted"] == 1
    row = deliverable[0]
    assert list(row.keys()) == _FOURTEEN            # exactly the 14 client columns
    assert row["Exam Name"] == "Exam X"
    assert row["College Name"] == "IIT Z"
    assert row["Closing Rank"] == 66
    assert row["Link - Data Taken from"] == "https://site.edu/cutoff"


def test_fill_cat3_no_search_result_yields_no_rows():
    prov, deliverable = fill_cat3(
        ["E"], year=None, search_fn=lambda q: [], fetch_fn=lambda u: (True, 1, True),
        extract_fn=lambda e, u: [{"Institute": "x"}])
    assert deliverable == []
    assert prov[0]["found"] is False and prov[0]["rows_extracted"] == 0


def test_fill_cat3_found_page_but_no_extractable_rows():
    prov, deliverable = fill_cat3(
        ["E"], year=None, search_fn=lambda q: ["https://u"],
        fetch_fn=lambda u: (True, 3, True), extract_fn=lambda e, u: [])
    assert deliverable == []
    assert prov[0]["found"] is True and prov[0]["rows_extracted"] == 0


def test_fill_cat3_tolerates_extractor_exception():
    def boom(exam, url):
        raise RuntimeError("bad page")
    prov, deliverable = fill_cat3(
        ["E"], year=None, search_fn=lambda q: ["https://u"],
        fetch_fn=lambda u: (True, 2, True), extract_fn=boom)
    assert deliverable == [] and prov[0]["rows_extracted"] == 0


def test_cat3_outputs_never_look_like_unified_cutoff_rows():
    """Provenance columns must be disjoint from the unified schema (no leakage)."""
    assert set(CAT3_PROVENANCE_COLUMNS).isdisjoint(_UNIFIED_SCHEMA)


def test_relevance_gate_rejects_misattributed_pages():
    """An obscure exam must not match a different famous exam's cutoff page."""
    # Real match: the exam's tokens are in the URL slug.
    assert _is_relevant("MIT World Peace University Entrance Test",
                        "https://zollege.in/mit-world-peace-university-mitwpu/cutoff")
    # Misattribution: a design test resolving to NIFT Delhi must be rejected.
    assert not _is_relevant("Vogue Institute of Art and Design Entrance Examination",
                            "https://x.com/national-institute-of-fashion-technology-delhi/cut-off")
    # Wrong campus: Sikkim Manipal vs MIT Manipal (only 'manipal' overlaps -> reject).
    assert not _is_relevant("Sikkim Manipal University Design Entrance Examination",
                            "https://x.com/manipal-institute-of-technology-mahe/cutoff")


def test_exam_from_query_and_relax():
    q = build_query("Some Exam", year=2025)
    assert _exam_from_query(q) == "Some Exam"
    relaxed = _relax_query(q)
    assert '"' not in relaxed and " OR " not in relaxed and "merit list" not in relaxed.lower()


def test_rank_urls_prefers_relevant_then_cutoff():
    urls = [
        "https://collegedunia.com/some-other-exam-cutoff",      # cutoff but irrelevant
        "https://zollege.in/mit-world-peace-university/cutoff",  # relevant + cutoff
        "https://wikipedia.org/MIT_WPU",                         # junk domain -> dropped
    ]
    ranked = _rank_urls(urls, exam="MIT World Peace University Entrance Test")
    assert ranked[0] == "https://zollege.in/mit-world-peace-university/cutoff"
    assert all("wikipedia" not in u for u in ranked)


def test_raw_to_unified_quality_gate():
    base = {"branch_or_course": "Computer Engineering",
            "table_caption": "MIT-WPU B.Tech Cutoff 2025", "closing_rank": 29442}
    assert _raw_to_unified(base, "MIT WPU")["ClosingRank"] == 29442
    # No rank/percentile -> dropped.
    assert _raw_to_unified({**base, "closing_rank": None}, "E") is None
    # Caption is not cutoff-related (a courses/dates table) -> dropped.
    assert _raw_to_unified({**base, "table_caption": "Admission Dates"}, "E") is None
    # Branch missing -> dropped.
    assert _raw_to_unified({**base, "branch_or_course": ""}, "E") is None
