"""Tests for best-effort enrichment of Website/SourceURL/City/Program."""

from __future__ import annotations

import pandas as pd

from cutoffs.enrich import (
    _category_group, _clean_text, _dedouble, _derive_city, _derive_program,
    enrich_frame,
)
from cutoffs.schema import normalize
from cutoffs.source import SourceMeta

_JOSAA_META = SourceMeta(
    name="josaa", exam="JEE Advanced / JEE Main", level="UG",
    body_label="JoSAA", website="https://josaa.nic.in/",
    source_url="https://josaa.admissions.nic.in/applicant/seatallotmentresult/",
)


def test_clean_text_dedoubles_and_collapses_linebreaks():
    # Real rows double each glyph preserving case; build it that way + a lone \n.
    clean = "015-Ch. Poly. College,"
    raw = "".join(ch * 2 for ch in clean) + "\n" + "".join(ch * 2 for ch in "Sriganganagar")
    assert _clean_text(raw) == "015-Ch. Poly. College, Sriganganagar"
    # plain mid-name line-break (no doubling) is collapsed to a single space
    assert _clean_text("Govt. Polytechnic College,\nSirohi") == \
        "Govt. Polytechnic College, Sirohi"


def test_enrich_frame_collapses_linebreaks_in_branch():
    df = normalize(pd.DataFrame({
        "Body": ["ICAR / NTA"], "Institute": ["Some College, Pune"],
        "Level": ["UG"], "Branch": ["AA- B.Sc. (Hons.)\nAgriculture"],
    }))
    out = enrich_frame(df)
    assert out["Branch"].iloc[0] == "AA- B.Sc. (Hons.) Agriculture"


def test_dedouble_collapses_glyph_doubled_text():
    assert _dedouble("BBiikkaanneerr") == "Bikaner"
    assert _dedouble("CCoolllleeggee,, AAllwwaarr") == "College, Alwar"
    # a stray un-doubled char (lone newline) is tolerated
    assert _dedouble("CCoolllleeggee,,\nJJaaiippuurr") == "College,\nJaipur"


def test_dedouble_leaves_normal_double_letters_intact():
    for word in ("College", "Bhilwara", "Alappuzha", "IIT Bombay", "Bengaluru",
                 "Male", "Female", "General", "OBC", "SC", "ST", "BOOK", "NOON"):
        assert _dedouble(word) == word


def test_dedouble_collapses_short_fully_doubled_codes():
    # Gender + reservation-category codes from the doubled Rajasthan DTE rows.
    for raw, clean in [("MMaallee", "Male"), ("FFeemmaallee", "Female"),
                       ("OOBBCC", "OBC"), ("SSCC", "SC"), ("SSTT", "ST"),
                       ("MMBBCC", "MBC")]:
        assert _dedouble(raw) == clean


def test_enrich_frame_dedoubles_gender_and_category():
    df = normalize(pd.DataFrame({
        "Body": ["Rajasthan DTE"], "Institute": ["Govt. Poly., Ajmer"],
        "Level": ["Diploma"], "Branch": ["Civil(GAS)"],
        "Category": ["OOBBCC"], "Gender": ["MMaallee"],
    }))
    out = enrich_frame(df)
    assert out["Gender"].iloc[0] == "Male"
    assert out["Category"].iloc[0] == "OBC"


def test_dedouble_rows_repairs_doubled_rank_digits():
    from cutoffs.schema import dedouble_rows
    df = pd.DataFrame({
        "Institute": ["Clean College, Pune", "CCoolllleeggee,, BBiikkaanneerr"],
        "Category": ["OBC", "OOBBCC"],
        "ClosingRank": ["2383", "55558844"],   # 2nd row's digits are doubled
    })
    out = dedouble_rows(df, ("Institute", "Category"))
    # Clean row untouched; doubled row's rank collapsed 55558844 -> 5584.
    assert out.loc[0, "ClosingRank"] == "2383"
    assert out.loc[1, "ClosingRank"] == "5584"
    assert out.loc[1, "Category"] == "OBC"


def test_derive_city_dedoubles_rajasthan_rows():
    inst = "000011--GGoovvtt.. PPoollyytteecchhnniicc CCoolllleeggee,, AAjjmmeerr"
    assert _derive_city(inst) == "Ajmer"


def test_derive_city_from_comma_segment():
    assert _derive_city("Government Engineering College, Kozhikkode") == "Kozhikkode"
    assert _derive_city("CIPET:IPT, BIHTA, PATNA") == "Patna"


def test_derive_city_strips_pincode_and_parens():
    got = _derive_city("West Bengal University of ..., KB Sarani, Kolkata-700037 (WB)")
    assert got == "Kolkata"


def test_derive_city_no_comma_takes_place_token_not_stopword():
    assert _derive_city("Indian Institute of Technology Bombay") == "Bombay"
    assert pd.isna(_derive_city("Jadavpur University"))  # trailing stopword -> NA


def test_derive_program_from_branch_and_level():
    assert _derive_program("UG", "CIVIL ENGINEERING") == "B.E./B.Tech"
    assert _derive_program("PG", "Structural Engineering") == "M.Tech"
    assert _derive_program("UG", "ARCHITECTURE (C)") == "B.Arch"
    assert _derive_program("Diploma", "Mechanical") == "Diploma"
    assert _derive_program("UG", "BA- BAMS") == "BAMS"
    assert _derive_program("UG", "B.Sc. (Hons.) Horticulture") == "B.Sc (Agriculture & allied)"


def test_enrich_frame_fills_links_by_source_name():
    df = normalize(pd.DataFrame({
        "Body": ["JoSAA"], "Institute": ["IIT Bombay"],
        "Level": ["UG"], "Branch": ["Computer Science and Engineering"],
    }))
    out = enrich_frame(df, _JOSAA_META)
    assert out["Website"].iloc[0] == "https://josaa.nic.in/"
    assert "seatallotmentresult" in out["SourceURL"].iloc[0]
    assert out["City"].iloc[0] == "Bombay"
    assert out["Program"].iloc[0] == "B.E./B.Tech"


def test_enrich_frame_preserves_existing_values():
    df = normalize(pd.DataFrame({
        "Body": ["JoSAA"], "Institute": ["IIT Bombay"], "City": ["Mumbai"],
        "Level": ["UG"], "Branch": ["CSE"],
    }))
    out = enrich_frame(df, _JOSAA_META)
    assert out["City"].iloc[0] == "Mumbai"  # not overwritten by derived "Bombay"


def test_category_group_normalizes_vocabularies():
    assert _category_group("OPEN") == "General"
    assert _category_group("SM") == "General"      # Kerala State Merit
    assert _category_group("EZ") == "OBC"          # Kerala Ezhava
    assert _category_group("OBC-NCL") == "OBC"
    assert _category_group("SC") == "SC"
    assert _category_group("EWS") == "EWS"
    assert _category_group("Unspecified") == "Unspecified"
    assert _category_group(None) == "Unspecified"
    assert _category_group("BH") == "Other"        # unmapped community code
    # Karnataka (KCET) codes: base GM/SC/ST/1/2A/.. with region/medium suffixes.
    assert _category_group("GMH") == "General"
    assert _category_group("GMRH") == "General"
    assert _category_group("SCKH") == "SC"
    assert _category_group("STH") == "ST"
    assert _category_group("2AG") == "OBC"
    assert _category_group("1R") == "OBC"
    assert _category_group("3BK") == "OBC"
    assert _category_group("STATE") == "Other"      # anchored: not read as ST
    # Maharashtra (MHT-CET) CAP stage codes.
    assert _category_group("GOPENS") == "General"
    assert _category_group("LOPENS") == "General"
    assert _category_group("GSCS") == "SC"
    assert _category_group("GSTS") == "ST"
    assert _category_group("GOBCS") == "OBC"
    assert _category_group("GVJS") == "OBC"
    assert _category_group("GNT1S") == "OBC"
    assert _category_group("GSEBCS") == "OBC"
    assert _category_group("TFWS") == "General"     # tuition-fee-waiver -> open


def test_enrich_frame_adds_category_group():
    df = normalize(pd.DataFrame({
        "Body": ["JoSAA"], "Institute": ["IIT Bombay"], "Level": ["UG"],
        "Branch": ["CSE"], "Category": ["OPEN"],
    }))
    out = enrich_frame(df, _JOSAA_META)
    assert out["CategoryGroup"].iloc[0] == "General"
