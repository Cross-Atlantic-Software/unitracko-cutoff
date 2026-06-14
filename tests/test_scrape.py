"""Tests for the generic HTML scraper, PDF framework, and generic source.

All network-free: they exercise the table->schema mapping on fixtures and assert
the tolerant (never-raise, empty-on-failure) contract.
"""

from __future__ import annotations

from cutoffs.adapters._pdf import parse_cutoff_pdf
from cutoffs.adapters.generic import GenericHTMLSource
from cutoffs.schema import COLUMNS
from cutoffs.scrape import (
    extract_tables,
    is_cutoff_table,
    map_table,
    _flatten_columns,
)

_CUTOFF_HTML = """
<html><body>
<table>
<tr><th>Institute</th><th>Branch</th><th>Category</th><th>Opening Rank</th><th>Closing Rank</th></tr>
<tr><td>IIT Example</td><td>CSE</td><td>OPEN</td><td>1</td><td>120</td></tr>
<tr><td>NIT Example</td><td>ECE</td><td>OBC</td><td>500</td><td>1,340</td></tr>
</table>
</body></html>
"""

_NOISE_HTML = """
<html><body>
<table><tr><th>Notice</th><th>Date</th></tr><tr><td>Holiday</td><td>2024</td></tr></table>
</body></html>
"""


def test_extract_and_detect_cutoff_table():
    tables = extract_tables(_CUTOFF_HTML)
    assert len(tables) == 1
    assert is_cutoff_table(_flatten_columns(tables[0]))


def test_noise_table_not_detected():
    tables = extract_tables(_NOISE_HTML)
    assert not is_cutoff_table(_flatten_columns(tables[0]))


def test_map_table_to_schema_with_comma_ranks():
    tables = extract_tables(_CUTOFF_HTML)
    out = map_table(tables[0], exam="Demo", body="DemoBody", year=2024)
    assert list(out.columns) == COLUMNS
    assert len(out) == 2
    assert int(out.iloc[1]["ClosingRank"]) == 1340  # comma stripped
    assert (out["Exam"] == "Demo").all()
    assert (out["Year"] == 2024).all()


def test_map_lone_rank_column_is_closing():
    html = ("<table><tr><th>College</th><th>Cutoff Rank</th></tr>"
            "<tr><td>ABC</td><td>900</td></tr></table>")
    out = map_table(extract_tables(html)[0], exam="X", body="X")
    assert int(out.iloc[0]["ClosingRank"]) == 900


def test_opening_cutoff_does_not_overwrite_closing():
    # Regression: "Opening Cutoff" matched _CLOSING (cut.?off), corrupting ranks.
    html = ("<table><tr><th>Institute</th><th>Opening Cutoff</th><th>Closing Cutoff</th></tr>"
            "<tr><td>A</td><td>50</td><td>500</td></tr>"
            "<tr><td>B</td><td>80</td><td>800</td></tr></table>")
    out = map_table(extract_tables(html)[0], exam="X", body="X")
    assert list(out["OpeningRank"]) == [50, 80]
    assert list(out["ClosingRank"]) == [500, 800]


def test_duplicate_columns_do_not_raise():
    # Regression: duplicate header names made df[col] a DataFrame -> ValueError.
    import pandas as pd
    dup = pd.DataFrame([["IIT", 100, 150]],
                       columns=["Institute", "Closing Rank", "Closing Rank"])
    out = map_table(dup, exam="X", body="X")  # must not raise
    assert list(out.columns) == COLUMNS
    assert int(out.iloc[0]["ClosingRank"]) == 100  # first of the duplicates


def test_level_and_state_threaded_through():
    html = ("<table><tr><th>College</th><th>Closing Rank</th></tr>"
            "<tr><td>ABC</td><td>900</td></tr></table>")
    out = map_table(extract_tables(html)[0], exam="X", body="X",
                    level="UG", state="Kerala")
    assert out.iloc[0]["Level"] == "UG"
    assert out.iloc[0]["State"] == "Kerala"


def test_extract_tables_tolerates_garbage():
    assert extract_tables("not html at all") == []
    assert extract_tables("") == []


def test_generic_source_bad_url_is_empty_not_error():
    src = GenericHTMLSource("X", "https://example.invalid/none", body="X")
    df = src.fetch_latest()
    assert list(df.columns) == COLUMNS
    assert df.empty


def test_pdf_parser_tolerates_missing_and_garbage():
    assert parse_cutoff_pdf("does_not_exist.pdf", exam="X").empty
    assert parse_cutoff_pdf(b"%PDF-garbage", exam="X").empty
