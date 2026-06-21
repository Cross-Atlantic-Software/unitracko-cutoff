"""Tests for the built-in adapters and the ingest layer."""

from __future__ import annotations

import cutoffs.adapters  # noqa: F401  (registers adapters)
from cutoffs import ingest
from cutoffs.registry import get_source, source_names
from cutoffs.schema import COLUMNS
from cutoffs.storage import read_parquet


def test_all_adapters_registered():
    assert {"josaa", "mhtcet", "kcet", "wbjee", "keam", "biharpoly", "tseamcet",
            "apeapcet", "uptac", "tnea", "gujacpc", "ojee",
            "jceceb"}.issubset(set(source_names()))


def test_jceceb_load_cached_is_jharkhand():
    df = get_source("jceceb").load_cached()
    assert list(df.columns) == COLUMNS
    assert (df["State"] == "Jharkhand").all()
    # cutoffs derived from allotment: every row has opening AND closing rank.
    assert df["OpeningRank"].notna().all() and df["ClosingRank"].notna().all()
    assert (df["ClosingRank"] >= df["OpeningRank"]).all()


def test_jceceb_allotment_header_detection():
    from cutoffs.adapters.jceceb import _allotment_columns
    hdr = _allotment_columns(["Sl. No.", "CML Rank", "Alloted Institute",
                              "Alloted Branch", "Seat Alloted Category"])
    assert hdr == {"rank": 1, "Institute": 2, "Branch": 3, "Category": 4}
    assert _allotment_columns(["1", "135", "BIT SINDRI", "CSE", "GEN"]) is None


def test_ojee_load_cached_is_odisha():
    df = get_source("ojee").load_cached()
    assert list(df.columns) == COLUMNS
    assert (df["State"] == "Odisha").all()
    assert df["Institute"].nunique() > 80
    assert df["ClosingRank"].notna().any()


def test_flattable_header_detection():
    from cutoffs.adapters._flattable import _header_indices
    colmap = [("institute name", "Institute"), ("stream", "Branch"),
              ("closing rank", "ClosingRank"), ("opening rank", "OpeningRank")]
    hdr = _header_indices(["INSTITUTE NAME", "STREAM", "OPENING RANK", "CLOSING RANK"], colmap)
    assert hdr == {"Institute": 0, "Branch": 1, "OpeningRank": 2, "ClosingRank": 3}
    # a data row (no header substrings) is not a header
    assert _header_indices(["IIT Foo", "CSE", "10", "500"], colmap) is None


def test_gujacpc_load_cached_is_gujarat():
    df = get_source("gujacpc").load_cached()
    assert list(df.columns) == COLUMNS
    assert (df["State"] == "Gujarat").all()
    assert df["Institute"].nunique() > 100
    # ACPC publishes both First (opening) and Last (closing) rank.
    assert df["OpeningRank"].notna().any() and df["ClosingRank"].notna().any()


def test_tnea_load_cached_is_tamil_nadu():
    df = get_source("tnea").load_cached()
    assert list(df.columns) == COLUMNS
    assert (df["State"] == "Tamil Nadu").all()
    assert df["Institute"].nunique() > 200
    assert df["ClosingRank"].notna().any()


def test_uptac_load_cached_has_colleges():
    df = get_source("uptac").load_cached()
    assert list(df.columns) == COLUMNS
    assert (df["State"] == "Uttar Pradesh").all()
    assert df["Institute"].nunique() > 300
    assert df["ClosingRank"].notna().any()


def test_uptac_parses_html_report():
    from cutoffs.adapters.uptac import parse_uptac_report
    html = """<table>
      <tr><th>Sr.No</th><th>Round</th><th>Institute</th><th>Program</th>
          <th>Stream</th><th>Quota</th><th>Category</th><th>Seat Gender</th>
          <th>Opening Rank</th><th>Closing Rank</th></tr>
      <tr><td>1</td><td>Round 1</td><td>ABC ENGG COLLEGE</td><td>B.Tech.</td>
          <td>Civil Engineering</td><td>Home State</td><td>BC(Girl)</td>
          <td>Female Seats</td><td>1000</td><td>2500</td></tr>
    </table>"""
    df = parse_uptac_report(html, year=2025, source_url="http://x")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["Institute"] == "ABC ENGG COLLEGE" and row["Branch"] == "Civil Engineering"
    assert row["ClosingRank"] == 2500 and row["Gender"] == "Female"


def test_tseamcet_apeapcet_load_cached_have_colleges():
    for name, state in [("tseamcet", "Telangana"), ("apeapcet", "Andhra Pradesh")]:
        df = get_source(name).load_cached()
        assert list(df.columns) == COLUMNS
        assert (df["State"] == state).all()
        assert df["Institute"].nunique() > 100
        assert df["ClosingRank"].notna().any()


def test_lastrank_rank_header_parsing():
    from cutoffs.adapters._lastrank import _rank_header
    assert _rank_header("OC\nBOYS") == ("OC", "Male")
    assert _rank_header("BC_A\nGIRLS") == ("BCA", "Female")
    assert _rank_header("OC_BO\nYS") == ("OC", "Male")   # header wrapped mid-word
    assert _rank_header("Institute Name") is None
    assert _rank_header("Affiliated To") is None


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
