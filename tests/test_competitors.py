"""Tests for the Category-2 competitor scrapers (pure-stdlib surface).

Covers the URL builders (slug extraction per site), the JSON-blob extractors
(``__NEXT_DATA__`` / ``window.INITIAL_STATE`` with nested braces), heading->table
attribution, rank coercion (sci-notation), and column-role detection. The live
fetch + pandas table parse run only in the build env.
"""
from __future__ import annotations

from cutoffs.competitors import RAW_COLUMNS
from cutoffs.competitors import careers360, collegedekho, collegedunia, run as comp_run, shiksha
from cutoffs.competitors._common import (
    balanced_json,
    category_columns,
    coerce_rank,
    detect_roles,
    extract_initial_state,
    extract_next_data,
    harvest_pdf_links,
    headings_before_tables,
)


# --------------------------------------------------------------------------
# URL builders
# --------------------------------------------------------------------------
def test_collegedunia_urls():
    assert collegedunia.cutoff_urls("https://collegedunia.com/exams/jee-main") == [
        "https://collegedunia.com/exams/jee-main/cutoff"]
    # search / course links have no exam slug -> no cutoff URL
    assert collegedunia.cutoff_urls("https://collegedunia.com/e-search?term=Foo+Bar") == []
    assert collegedunia.cutoff_urls("https://collegedunia.com/courses/acca") == []


def test_collegedekho_urls_include_year_archives():
    urls = collegedekho.cutoff_urls("https://www.collegedekho.com/exam/kcet",
                                    years=(2024, 2023))
    assert urls[0] == "https://www.collegedekho.com/exam/kcet/cutoff"
    assert "https://www.collegedekho.com/exam/kcet/cutoff-2024-esp" in urls
    assert "https://www.collegedekho.com/exam/kcet/cutoff-2023-esp" in urls
    assert collegedekho.cutoff_urls("https://www.collegedekho.com/courses/x") == []


def test_careers360_urls_preserve_vertical_and_try_both_variants():
    urls = careers360.cutoff_urls("https://medicine.careers360.com/exams/neet")
    assert "https://medicine.careers360.com/articles/neet-cutoff" in urls
    assert "https://medicine.careers360.com/articles/neet-cut-off" in urls
    # an article URL with a -cutoff suffix yields the bare slug, not "neet-cutoff"
    urls2 = careers360.cutoff_urls("https://engineering.careers360.com/articles/jee-main-cutoff")
    assert "https://engineering.careers360.com/articles/jee-main-cutoff" in urls2


def test_shiksha_urls_use_exam_cutoff_suffix():
    assert shiksha.cutoff_urls("https://www.shiksha.com/engineering/mht-cet-exam") == [
        "https://www.shiksha.com/engineering/mht-cet-exam-cutoff"]
    # already a cutoff hub -> idempotent
    assert shiksha.cutoff_urls("https://www.shiksha.com/engineering/kcet-exam-cutoff") == [
        "https://www.shiksha.com/engineering/kcet-exam-cutoff"]
    # generic search landing -> no slug
    assert shiksha.cutoff_urls("https://www.shiksha.com/search?q=Foo%20Bar") == []


# --------------------------------------------------------------------------
# JSON blob extraction
# --------------------------------------------------------------------------
def test_extract_next_data():
    html = '<html><script id="__NEXT_DATA__" type="application/json">{"props":{"x":1}}</script></html>'
    assert extract_next_data(html) == {"props": {"x": 1}}
    assert extract_next_data("<html>no blob</html>") is None


def test_balanced_json_handles_nested_braces_and_strings():
    text = 'prefix = {"a": {"b": "}"}, "c": [1, {"d": 2}]} ; trailing'
    blob = balanced_json(text)
    import json
    assert json.loads(blob) == {"a": {"b": "}"}, "c": [1, {"d": 2}]}


def test_extract_initial_state():
    html = ('<script>window.INITIAL_STATE = '
            '{"page":{"content":"<table><tr><td>1</td></tr></table>"},"n":7};</script>')
    state = extract_initial_state(html)
    assert state["n"] == 7
    assert "<table" in state["page"]["content"]


def test_careers360_digs_article_html_out_of_state():
    state = {"a": {"content": "<table><tr><td>x</td></tr></table>"},
             "b": {"body": "no table here"}}
    html = careers360._article_html_from_state(state)
    assert html is not None and "<table" in html


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
def test_coerce_rank():
    assert coerce_rank("3.16E+04") == 31600
    assert coerce_rank("1,234") == 1234
    assert coerce_rank(" 56 ") == 56
    assert coerce_rank("234.0") == 234
    for bad in ("", "-", "NA", "TBA", None):
        assert coerce_rank(bad) is None


def test_headings_before_tables():
    html = ("<h2>NIT Trichy 2024</h2><table><tr><th>Cat</th></tr></table>"
            "<p>blah</p><h3>NIT Warangal 2024</h3><table><tr><th>Cat</th></tr></table>")
    assert headings_before_tables(html) == ["NIT Trichy 2024", "NIT Warangal 2024"]


def test_category_columns():
    cols = ["College", "Branch", "General", "OBC-NCL", "SC", "ST", "EWS", "Closing Rank"]
    assert category_columns(cols) == ["General", "OBC-NCL", "SC", "ST", "EWS"]


def test_detect_roles():
    roles = detect_roles(["Institute", "Opening Rank", "Closing Rank", "Category", "Round"])
    assert roles["institute_name"] == "Institute"
    assert roles["opening_rank"] == "Opening Rank"
    assert roles["closing_rank"] == "Closing Rank"
    assert roles["category"] == "Category"
    assert roles["counselling_round"] == "Round"


def test_harvest_pdf_links():
    html = '<a href="/files/r1.pdf">R1</a> <a href="https://x.org/r2.pdf?v=2">R2</a>'
    links = harvest_pdf_links(html, "https://site.com/page")
    assert "https://site.com/files/r1.pdf" in links
    assert "https://x.org/r2.pdf?v=2" in links


def test_raw_columns_superset_has_key_fields():
    for col in ("source_competitor", "exam", "institute_name", "category",
                "opening_rank", "closing_rank", "cutoff_percentile", "raw_cells"):
        assert col in RAW_COLUMNS


# --------------------------------------------------------------------------
# run.py target selection — the client's "all exams with a competitor link".
# --------------------------------------------------------------------------
_SEG = [
    {"exam": "A", "category": "cat1", "collegedunia": "https://x", "shiksha": ""},
    {"exam": "B", "category": "cat2", "collegedunia": "https://y", "shiksha": "https://z"},
    {"exam": "C", "category": "cat3", "collegedunia": "", "shiksha": ""},
]


def test_links_scope_selects_every_exam_with_the_link():
    # categories=None -> every exam carrying the link, regardless of category
    assert comp_run._CATEGORY_SETS["links"] is None
    got = sorted(e for e, _ in comp_run._targets(_SEG, "collegedunia", None))
    assert got == ["A", "B"]          # A is cat1 but still has the link


def test_cat2_scope_narrows_to_bucket():
    got = [e for e, _ in comp_run._targets(_SEG, "collegedunia", {"cat2"})]
    assert got == ["B"]               # cat1 exam A excluded


def test_default_category_is_links():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", choices=list(comp_run._CATEGORY_SETS), default="links")
    assert parser.parse_args([]).category == "links"
