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


def test_kcet_load_cached_has_full_college_coverage():
    # KCET now ships the parsed official KEA PDF snapshot (hundreds of colleges),
    # not just the 5-college curated sample.
    df = get_source("kcet").load_cached()
    assert list(df.columns) == COLUMNS
    assert (df["State"] == "Karnataka").all()
    assert df["Institute"].nunique() > 100
    assert df["ClosingRank"].notna().any()
    # Karnataka reservation codes are grouped, not dumped into "Other".
    from cutoffs.enrich import enrich_frame
    groups = set(enrich_frame(df, get_source("kcet").meta)["CategoryGroup"])
    assert {"General", "OBC", "SC", "ST"}.issubset(groups)


def test_kcet_dedup_drops_identical_cutoff_rows():
    import pandas as pd

    from cutoffs.adapters.kcet import _dedup
    row = {"Institute": "X", "Branch": "CS", "Category": "GMG", "Quota": "General",
           "Year": 2024, "ClosingRank": 1000}
    out = _dedup(pd.DataFrame([row, dict(row), {**row, "ClosingRank": 2000}]))
    assert len(out) == 2  # the exact duplicate is dropped, the differing rank kept


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
    # Now ships the parsed official CAP-round PDF snapshot (hundreds of colleges).
    assert df["Institute"].nunique() > 100
    assert df["ClosingRank"].notna().any()


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


def test_ingest_writes_freshness_sidecar(tmp_path):
    path = tmp_path / "out.parquet"
    df = ingest.run(names=["mhtcet"], mode="cached", path=path)
    meta = ingest.load_meta(path)
    assert (path.with_name("dataset_meta.json")).exists()
    assert meta["mode"] == "cached"
    assert meta["rows"] == len(df)
    assert meta["sources"] == 1
    assert meta["generated_at"]  # ISO timestamp present


def test_load_meta_missing_returns_empty(tmp_path):
    assert ingest.load_meta(tmp_path / "absent.parquet") == {}


def test_enrichment_columns_present_after_ingest(tmp_path):
    path = tmp_path / "out.parquet"
    df = ingest.run(names=["josaa"], mode="cached", path=path)
    # B1/A6: links come from SourceMeta; CategoryGroup is derived.
    assert (df["Website"] == "https://josaa.nic.in/").all()
    assert df["CategoryGroup"].notna().any()
