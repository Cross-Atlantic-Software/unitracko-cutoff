"""Tests for the built-in adapters and the ingest layer."""

from __future__ import annotations

import cutoffs.adapters  # noqa: F401  (registers adapters)
from cutoffs import ingest
from cutoffs.registry import get_source, source_names
from cutoffs.schema import COLUMNS
from cutoffs.storage import read_parquet


def test_all_adapters_registered():
    assert {"josaa", "mhtcet", "kcet", "wbjee", "keam", "biharpoly"}.issubset(set(source_names()))


def test_real_pdf_adapters_have_rows():
    # KEAM + Bihar Poly ship real, parsed PDF data (hundreds/thousands of rows).
    keam = get_source("keam").load_cached()
    bihar = get_source("biharpoly").load_cached()
    assert len(keam) > 1000 and keam["Institute"].nunique() > 50
    assert len(bihar) > 200 and bihar["ClosingRank"].notna().any()


def test_josaa_load_cached_schema_and_rows():
    df = get_source("josaa").load_cached()
    assert list(df.columns) == COLUMNS
    assert len(df) > 0
    assert (df["Body"] == "JoSAA").all()
    # ranks coerced to integers
    assert str(df["ClosingRank"].dtype) == "Int64"
    assert df["ClosingRank"].notna().any()


def test_mhtcet_load_cached_is_maharashtra():
    df = get_source("mhtcet").load_cached()
    assert list(df.columns) == COLUMNS
    assert (df["State"] == "Maharashtra").all()


def test_fetch_latest_never_returns_empty():
    # Best-effort live; must fall back to cached, never empty/raise.
    df = get_source("josaa").fetch_latest()
    assert list(df.columns) == COLUMNS
    assert len(df) > 0


def test_ingest_all_writes_parquet(tmp_path):
    path = tmp_path / "out.parquet"
    df = ingest.run(names=None, mode="cached", path=path)
    assert path.exists()
    assert list(df.columns) == COLUMNS
    bodies = set(df["Body"].dropna().unique())
    assert {"JoSAA", "MHT-CET"}.issubset(bodies)
    assert len(read_parquet(path)) == len(df)


def test_ingest_individual_body(tmp_path):
    path = tmp_path / "out.parquet"
    df = ingest.run(names=["mhtcet"], mode="cached", path=path)
    assert set(df["Body"].unique()) == {"MHT-CET"}


def test_ingest_available_lists_sources():
    assert "josaa" in ingest.available()
