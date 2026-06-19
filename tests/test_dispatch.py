"""Tests for the Category-1 bucket -> fetcher dispatch decision layer.

Pure standard library — exercises only ``strategy_for`` / ``fetcher_name`` /
``is_dead`` / ``load_probe_buckets`` (no pandas, no network). The actual fetch in
``dispatch_fetch`` is covered in the build env where httpx/pdfplumber exist.
"""
from __future__ import annotations

from cutoffs.dispatch import (
    HTML,
    JS,
    NONE,
    PDF,
    PROBE_PATH,
    fetcher_name,
    is_dead,
    load_probe_buckets,
    strategy_for,
)

# Every bucket actually observed in data/source_probe.csv -> expected fetcher.
_EXPECTED = {
    "html_table_rank": HTML,
    "html_rank_notable": HTML,
    "html_other": HTML,
    "html_table_norank": HTML,
    "js_only": JS,
    "pdf": PDF,
    "http_404": NONE,
    "http_403": NONE,
    "http_500": NONE,
    "http_503": NONE,
    "error": NONE,
    "no_url": NONE,
    "non_html": NONE,
}


def test_every_observed_bucket_maps_to_expected_fetcher():
    for bucket, fetcher in _EXPECTED.items():
        assert fetcher_name(bucket) == fetcher, bucket


def test_dead_buckets_are_dead_and_live_ones_are_not():
    for bucket, fetcher in _EXPECTED.items():
        assert is_dead(bucket) is (fetcher == NONE), bucket


def test_unknown_and_blank_buckets_default_to_dead():
    for bucket in ("", "   ", None, "weird_new_bucket", "no_url"):
        assert fetcher_name(bucket) == NONE
        assert is_dead(bucket) is True


def test_prefix_rules():
    # Unseen html_* variant still routes to the HTML scraper.
    assert fetcher_name("html_something_new") == HTML
    # Any http_* status code is dead.
    assert fetcher_name("http_418") == NONE
    # pdf* routes to the PDF parser.
    assert fetcher_name("pdf_multipage") == PDF


def test_strategy_timeouts_and_retries():
    assert strategy_for("html_table_rank").retries == 1
    js = strategy_for("js_only")
    assert js.fetcher == JS and js.retries == 0
    pdf = strategy_for("pdf")
    assert pdf.fetcher == PDF and pdf.timeout >= 45.0 and pdf.retries >= 2
    assert strategy_for("http_404").is_dead is True


def test_probe_buckets_load_and_cover_cat1_links():
    """The real probe file loads and every bucket in it resolves without error."""
    buckets = load_probe_buckets()
    assert PROBE_PATH.exists()
    assert len(buckets) > 200
    # Every distinct bucket value classifies to one of the four fetcher keys.
    for b in set(buckets.values()):
        assert fetcher_name(b) in {HTML, JS, PDF, NONE}
