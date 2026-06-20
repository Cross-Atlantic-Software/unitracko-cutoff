"""Tests for the exam catalog (breadth layer)."""

from __future__ import annotations

from cutoffs import catalog
from cutoffs.catalog import (
    CATALOG_COLUMNS,
    build_catalog,
    classify_category,
    classify_state,
)


def test_build_catalog_shape_and_columns():
    df = build_catalog()
    assert list(df.columns) == CATALOG_COLUMNS
    assert len(df) > 300  # the sheet has 317 exams
    # every exam classified into a non-empty category/level/state
    assert df["Category"].notna().all()
    assert (df["Level"] != "").all()
    assert (df["State"] != "").all()


def test_category_classification_examples():
    assert classify_category("Kerala Law Entrance Examination") == "Law"
    assert classify_category("Andhra Pradesh Polytechnic Entrance Examination") == "Polytechnic & Diploma"
    assert classify_category("National Institute of Fashion Technology Entrance Examination") == "Design"
    assert classify_category("Bihar Engineering Entrance Examination") == "Engineering & Technology"
    assert classify_category("All India Veterinary Entrance Test") == "Veterinary"


def test_flagship_joint_entrance_exams_are_engineering():
    # Regression: JEE/WBJEE full names fell into the "Multidisciplinary" catch-all.
    assert classify_category("Joint Entrance Examination (Main)") == "Engineering & Technology"
    assert classify_category("Joint Entrance Examination (Advanced)") == "Engineering & Technology"
    assert classify_category("West Bengal Joint Entrance Examination") == "Engineering & Technology"


def test_state_classification_examples():
    assert classify_state("West Bengal Joint Entrance Examination") == "West Bengal"
    assert classify_state("Maharashtra Common Entrance Test") == "Maharashtra"
    assert classify_state("Joint Entrance Examination") == "All India"


def test_state_institution_lookup():
    # Regression: city/university-named exams were silently tagged "All India".
    assert classify_state("Guru Gobind Singh Indraprastha University Common Entrance Test") == "Delhi"
    assert classify_state("Cochin University of Science and Technology Marine Engineering") == "Kerala"


def test_combined_cet_routes_to_engineering():
    # Regression: multi-stream CETs lost Engineering to Pharmacy/Medical.
    assert classify_category("Andhra Pradesh Engineering and Agriculture and Pharmacy Common Entrance Test") == "Engineering & Technology"
    assert classify_category("Telangana State Engineering Agriculture and Medical Common Entrance Test") == "Engineering & Technology"


def test_category_edge_cases():
    from cutoffs.catalog import _classify_level
    assert classify_category("Galileo Global Distribution System Certification Examination") == "Aviation & Maritime"
    assert classify_category("Indian Institute of Foreign Trade Entrance Examination") == "Management"
    assert classify_category("Rashtriya Raksha University (Police)") == "Defence & Security"
    # level: professional stages are Certification, institute-name "Postgraduate" is not PG
    assert _classify_level("Chartered Accountancy Final Examination") == "Certification"
    assert _classify_level("Company Secretary Executive Entrance Test") == "Certification"
    assert _classify_level("Jawaharlal Institute of Postgraduate Medical Education and Research Nursing Entrance Examination") == "UG"


def test_scrapeable_status_present():
    df = build_catalog()
    # probe folded in -> at least some HTML-scrapeable, some pdf/dead buckets
    statuses = set(df["Scrapeable"])
    assert "scrapeable" in statuses or df["DataFormat"].eq("html").any()


def test_reference_metadata_folded_in():
    df = build_catalog()
    jee = df[df["Exam"].str.contains("Joint Entrance Examination", regex=False)]
    assert not jee.empty
    assert jee["Body"].str.contains("JoSAA", na=False).any()


def test_write_and_load_roundtrip(tmp_path):
    path = tmp_path / "catalog.parquet"
    written = catalog.write_catalog(path)
    loaded = catalog.load_catalog(path)
    assert len(written) == len(loaded)
    assert list(loaded.columns) == CATALOG_COLUMNS


def test_apply_enrichment_precedence_and_unescape():
    # Build a tiny frame with one row that has NO existing body and one that does.
    df = build_catalog().copy()
    no_body = df[df["Body"].astype(str).str.strip() == ""].iloc[0]["Exam"]
    has_body = df[df["Body"].astype(str).str.strip() != ""].iloc[0]
    records = [
        {"exam": no_body, "body": "Some Board &amp; Council",
         "level": "PG", "metric": "Percentile", "scope": "x &amp; y"},
        {"exam": has_body["Exam"], "body": "Different Body",
         "level": "Diploma", "metric": "Score", "scope": "note"},
    ]
    out = catalog._apply_enrichment(df, records)
    r1 = out[out["Exam"] == no_body].iloc[0]
    r2 = out[out["Exam"] == has_body["Exam"]].iloc[0]
    # Metric/Notes/Level always from enrichment; HTML entities unescaped.
    assert r1["Metric"] == "Percentile" and r1["Level"] == "PG"
    assert r1["Notes"] == "x & y"               # unescaped
    assert r1["Body"] == "Some Board & Council"  # filled (was empty) + unescaped
    # Existing curated Body is preserved (reference wins over enrichment).
    assert r2["Body"] == has_body["Body"]


def test_enrichment_auto_applied_in_build():
    # the bundled enrichment.json should fill most bodies/metrics on a clean build
    df = build_catalog()
    assert (df["Metric"].astype(str).str.strip() != "").sum() > 200
    assert (df["Body"].astype(str).str.strip() != "").sum() > 200


_AGGREGATORS = (
    "shiksha.com", "careers360.com", "collegedekho.com", "getmyuni.com",
    "entrancezone.com", "collegepravesh.com", "collegeforme.in", "collegedunia.com",
    "aglasem.com", "embibe.com",
)


def test_only_official_links_shown():
    # Official-links overlay: no aggregator domains in either link column.
    df = build_catalog()
    for col in ("Homepage", "CutoffURL"):
        for url in df[col].dropna().astype(str):
            assert not any(a in url.lower() for a in _AGGREGATORS), f"aggregator in {col}: {url}"
    # overlay also fills acronyms and keeps URLs https/empty
    assert (df["Acronym"].astype(str).str.strip() != "").sum() > 50
    bad = [u for u in df["Homepage"].dropna().astype(str)
           if u and not u.lower().startswith("http")]
    assert bad == []


def test_cutoff_status_and_aggregators_folded_in():
    # The richer EXAMlinkssheet overlay adds a curated status + aggregator links.
    df = build_catalog()
    from cutoffs.catalog import AGGREGATOR_COLUMNS
    assert "CutoffStatus" in df.columns
    statuses = set(df["CutoffStatus"])
    assert {"Official Cutoff", "Official Merit List", "No Cutoff Exists"} <= statuses
    # aggregator columns exist and carry real http(s) fallback links
    for col in AGGREGATOR_COLUMNS:
        assert col in df.columns
        assert df[col].astype(str).str.startswith("http").sum() > 50
    # aggregators must NOT leak into the official link columns (policy preserved)
    for col in ("Homepage", "CutoffURL"):
        for url in df[col].dropna().astype(str):
            assert not any(a in url.lower() for a in _AGGREGATORS)


def test_apply_links_blanks_and_overrides():
    df = build_catalog().head(30).copy()
    target = df.iloc[0]["Exam"]
    links = [{"exam": target, "homepage": "https://official.gov.in/",
              "cutoff": "", "acronym": "OFF"}]
    out = catalog._apply_links(df, links)
    row = out[out["Exam"] == target].iloc[0]
    assert row["Homepage"] == "https://official.gov.in/"
    assert row["CutoffURL"] == ""          # blanked, official-only
    assert row["Acronym"] == "OFF"
