"""Tests for the offline competitor URL resolver (pure stdlib, no network)."""
from __future__ import annotations

from cutoffs.competitors import _resolve as R
from cutoffs.competitors import careers360, collegedekho, collegedunia, shiksha


# --- the resolver primitives ----------------------------------------------
def test_slugify_normalizes_and_hyphenates():
    assert R.slugify("All India Veterinary Entrance Test") == "all-india-veterinary-entrance-test"
    assert R.slugify("AMU  B.A. LL.B") == "amu-b-a-ll-b"
    assert R.slugify("") == ""


def test_slugify_can_drop_noise_words():
    assert R.slugify("All India Veterinary Entrance Test", drop=R._SLUG_NOISE) == "veterinary"


def test_extract_search_term_reads_term_and_q():
    assert R.extract_search_term(
        "https://collegedunia.com/e-search?term=All+India+Veterinary") == "All India Veterinary"
    assert R.extract_search_term("https://www.shiksha.com/search?q=ACET") == "ACET"
    assert R.extract_search_term("https://x.com/exams/acet") is None


def test_acronym_of_significant_words():
    assert R.acronym("All India Veterinary Entrance Test") == "aivet"
    assert R.acronym("Common Law Admission Test") == "clat"
    assert R.acronym("Acet") is None          # single word -> no acronym


def test_candidate_slugs_prefers_search_term_then_exam():
    slugs = R.candidate_slugs(
        "https://collegedunia.com/e-search?term=All+India+Veterinary+Entrance+Test",
        "All India Veterinary Entrance Test")
    assert "all-india-veterinary-entrance-test" in slugs
    assert "aivet" in slugs
    assert len(slugs) <= 4


def test_candidate_slugs_from_exam_when_no_search_term():
    slugs = R.candidate_slugs("https://collegedunia.com/courses/foo", "Common Law Admission Test")
    assert "common-law-admission-test" in slugs
    assert "clat" in slugs


# --- the per-competitor fallbacks -----------------------------------------
def test_collegedunia_exact_path_still_wins():
    assert collegedunia.cutoff_urls("https://collegedunia.com/exams/acet") == [
        "https://collegedunia.com/exams/acet/cutoff"]


def test_collegedunia_falls_back_on_search_link():
    urls = collegedunia.cutoff_urls(
        "https://collegedunia.com/e-search?term=All+India+Veterinary",
        exam="All India Veterinary Entrance Test")
    assert urls                                      # no longer empty
    assert all(u.endswith("/cutoff") for u in urls)
    assert "https://collegedunia.com/exams/aivet/cutoff" in urls


def test_collegedekho_falls_back_and_keeps_year_archives():
    urls = collegedekho.cutoff_urls(
        "https://www.collegedekho.com/e-search?q=ACET", exam="Actuarial Common Entrance Test")
    assert any(u.endswith("/cutoff") for u in urls)
    assert any("-esp" in u for u in urls)            # year archives still generated


def test_careers360_falls_back_with_both_suffix_variants():
    urls = careers360.cutoff_urls(
        "https://www.careers360.com/courses/x", exam="Common Law Admission Test")
    assert any(u.endswith("-cutoff") for u in urls)
    assert any(u.endswith("-cut-off") for u in urls)


def test_shiksha_falls_back_across_streams_but_stays_bounded():
    urls = shiksha.cutoff_urls(
        "https://www.shiksha.com/search?q=ACET", exam="Actuarial Common Entrance Test")
    assert urls
    assert all(u.endswith("-exam-cutoff") for u in urls)
    assert len(urls) <= 2 * len(shiksha._STREAMS)    # slugs capped at 2


def test_exact_path_links_are_unaffected_by_fallback():
    # a real path link must produce exactly the canonical URL, no slug guessing:
    assert collegedekho.cutoff_urls("https://www.collegedekho.com/exam/jee-main")[0] == \
        "https://www.collegedekho.com/exam/jee-main/cutoff"
    assert shiksha.cutoff_urls("https://www.shiksha.com/engineering/jee-main-exam") == [
        "https://www.shiksha.com/engineering/jee-main-exam-cutoff"]
