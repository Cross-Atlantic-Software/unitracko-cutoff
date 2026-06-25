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
    _rows_from_table,
    balanced_json,
    category_columns,
    coerce_rank,
    detect_roles,
    extract_initial_state,
    extract_next_data,
    harvest_pdf_links,
    headings_before_tables,
    looks_like_percentile,
    rank_range,
)


# --------------------------------------------------------------------------
# URL builders
# --------------------------------------------------------------------------
def test_collegedunia_urls():
    assert collegedunia.cutoff_urls("https://collegedunia.com/exams/jee-main") == [
        "https://collegedunia.com/exams/jee-main/cutoff"]
    # a search link with a term now resolves via the offline slug resolver:
    assert "https://collegedunia.com/exams/foo-bar/cutoff" in \
        collegedunia.cutoff_urls("https://collegedunia.com/e-search?term=Foo+Bar")
    # a bare link with neither a search term nor an exam name -> still nothing to derive:
    assert collegedunia.cutoff_urls("https://collegedunia.com/courses/acca") == []


def test_collegedekho_urls_include_year_archives():
    urls = collegedekho.cutoff_urls("https://www.collegedekho.com/exam/kcet",
                                    years=(2024, 2023))
    assert urls[0] == "https://www.collegedekho.com/exam/kcet/cutoff"
    assert "https://www.collegedekho.com/exam/kcet/cutoff-2024-esp" in urls
    assert "https://www.collegedekho.com/exam/kcet/cutoff-2023-esp" in urls
    assert collegedekho.cutoff_urls("https://www.collegedekho.com/courses/x") == []


def test_collegedekho_derived_slug_skips_archives_on_404(monkeypatch):
    """A resolver-derived slug whose current-year page 404s must NOT fan out to the
    year archives — a wrong guess costs one GET, not 1 + len(years)."""
    from cutoffs.competitors import _common

    seen: list[str] = []

    def fake_fetch(url, **_):
        seen.append(url)
        return ""  # every page 404s -> empty html

    monkeypatch.setattr(_common, "fetch_html", fake_fetch)
    # search-landing link (no /exam/<slug>) -> slugs are derived, all 404.
    collegedekho.scrape("https://www.collegedekho.com/e-search?q=Foo+Bar+Exam",
                        "Foo Bar Exam", years=(2024, 2023))
    # only the per-slug current-year /cutoff probes, never a -esp archive.
    assert seen and all(u.endswith("/cutoff") for u in seen)


def test_collegedekho_path_slug_always_fetches_archives(monkeypatch):
    """A known-good path slug fetches the full archive set even if a page is empty."""
    from cutoffs.competitors import _common

    seen: list[str] = []

    def fake_fetch(url, **_):
        seen.append(url)
        return ""

    monkeypatch.setattr(_common, "fetch_html", fake_fetch)
    collegedekho.scrape("https://www.collegedekho.com/exam/kcet", "KCET",
                        years=(2024, 2023))
    assert "https://www.collegedekho.com/exam/kcet/cutoff-2024-esp" in seen
    assert "https://www.collegedekho.com/exam/kcet/cutoff-2023-esp" in seen


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
    # a search landing with a query now resolves via the offline resolver (slug x
    # common streams); a bare /search with no query and no exam stays empty.
    resolved = shiksha.cutoff_urls("https://www.shiksha.com/search?q=Foo%20Bar")
    assert "https://www.shiksha.com/engineering/foo-bar-exam-cutoff" in resolved
    assert shiksha.cutoff_urls("https://www.shiksha.com/search") == []


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


# --------------------------------------------------------------------------
# New parsing helpers (range / percentile / anchored year / negative rank)
# --------------------------------------------------------------------------
def test_coerce_rank_negative_reads_as_positive():
    assert coerce_rank("-5") == 5            # ranks are never negative


def test_rank_range():
    assert rank_range("200-500") == (200, 500)
    assert rank_range("1,200 to 3,400") == (1200, 3400)
    assert rank_range("200 – 500") == (200, 500)   # en-dash
    assert rank_range("500") is None
    assert rank_range(None) is None


def test_looks_like_percentile():
    assert looks_like_percentile("99.87")
    assert looks_like_percentile("100.0")
    assert not looks_like_percentile("50")       # integer rank, no decimal
    assert not looks_like_percentile("1234.5")   # > 100 -> a rank, not a percentile
    assert not looks_like_percentile("")


def test_detect_roles_year_is_anchored():
    # a standalone year column is the year column...
    assert detect_roles(["2024"]).get("year") == "2024"
    # ...but "Branch 2024" is a branch, not a year column (no substring match)
    roles = detect_roles(["Branch 2024"])
    assert roles.get("year") is None
    assert roles.get("branch_or_course") == "Branch 2024"


def test_caption_attaches_to_own_table_not_next():
    html = ("<h2>Heading A</h2>"
            "<table><caption>Real Caption</caption><tr><th>C</th></tr></table>"
            "<table><tr><th>C</th></tr></table>")
    # the caption stays on its own table; the next table falls back to the heading
    assert headings_before_tables(html) == ["Real Caption", "Heading A"]


# --------------------------------------------------------------------------
# _rows_from_table — the wide->long melt / role logic (previously untested).
# --------------------------------------------------------------------------
class _StubTable:
    """Minimal stand-in for a pandas table: ``.columns`` + ``.iterrows()`` yielding
    positional value lists (matching how ``_rows_from_table`` consumes a row)."""

    def __init__(self, columns, rows):
        self.columns = list(columns)
        self._rows = rows

    def iterrows(self):
        for i, r in enumerate(self._rows):
            yield i, list(r)


def _rows(columns, rows, *, caption="", year=None):
    return _rows_from_table(
        _StubTable(columns, rows), idx=0, caption=caption, default_pdf=None,
        competitor="cd", exam="X", slug="x", page_url="http://x",
        page_type="exam_cutoff", year=year)


def test_wide_category_table_is_melted_one_row_per_category():
    rows = _rows(["Institute", "Open", "OBC", "SC"],
                 [["NIT Trichy", "1200", "3400", "9000"]])
    by_cat = {r["category"]: r for r in rows}
    assert set(by_cat) == {"Open", "OBC", "SC"}        # Open kept (real wide table)
    assert by_cat["Open"]["closing_rank"] == 1200
    assert by_cat["OBC"]["closing_rank"] == 3400
    assert by_cat["SC"]["institute_name"] == "NIT Trichy"


def test_open_close_columns_are_not_melted_as_categories():
    # HIGH bug: "Open" matches both the opening-rank role and the category regex.
    # A lone Open beside a Close is the opening-rank column, not a category.
    rows = _rows(["Institute", "Open", "Close"], [["IIT Delhi", "50", "1200"]])
    assert len(rows) == 1
    r = rows[0]
    assert r["opening_rank"] == 50
    assert r["closing_rank"] == 1200
    assert not r["category"]                            # never melted into "Open"


def test_percentile_cells_not_rounded_into_closing_rank():
    rows = _rows(["College", "General", "OBC"], [["COEP", "99.87", "98.5"]])
    by_cat = {r["category"]: r for r in rows}
    assert by_cat["General"]["cutoff_percentile"] == "99.87"
    assert by_cat["General"]["closing_rank"] is None   # not coerced to 100
    assert by_cat["OBC"]["cutoff_percentile"] == "98.5"


def test_duplicate_headers_survive_losslessly_in_raw_cells():
    import json
    rows = _rows(["College", "Rank", "Rank"], [["X", "100", "200"]])
    cells = json.loads(rows[0]["raw_cells"])
    assert cells["Rank"] == "100"
    assert cells["Rank.1"] == "200"                     # 2nd dup not dropped


def test_range_cell_splits_into_opening_closing_and_keeps_raw():
    rows = _rows(["Institute", "Closing Rank"], [["X", "200-500"]])
    r = rows[0]
    assert r["rank_range_raw"] == "200-500"
    assert r["opening_rank"] == 200
    assert r["closing_rank"] == 500
