"""Offline URL resolution for competitor links that carry no usable slug.

Many segmentation links are *search-landing* pages (``/e-search?term=...``,
``/search?q=...``) or ``/courses/`` pages, so the per-site ``cutoff_urls`` finds no
slug in the path and returns ``[]`` — the exam never resolves to a cutoff page even
though the site almost certainly has one. But we always know the exam NAME (and
often the search term embedded in the URL), so we can *derive* candidate slugs and
let each competitor build its canonical cutoff URL(s) from them.

Everything here is pure stdlib string work — no network — so it's deterministic and
fully testable. The derived URLs are only *candidates*: the scrape validates them by
whether the page actually returns cutoff tables, so a wrong guess costs one 404, not
a bad row. Keep ``max_slugs`` small to stay polite.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qs, urlparse

# Filler words that don't help (or actively hurt) slug/acronym matching.
_STOP = {"the", "of", "for", "and", "in", "a", "an", "to", "on"}
# Words sites routinely drop from exam slugs (e.g. "…-entrance-exam" -> "…").
_SLUG_NOISE = {"entrance", "exam", "examination", "test", "common", "joint",
               "admission", "national", "all", "india"}

_SEARCH_PARAMS = ("term", "q", "query", "search", "keyword")


def slugify(text: str, *, sep: str = "-", drop: set[str] | None = None) -> str:
    """Lowercase ASCII slug: 'All India Vet Test' -> 'all-india-vet-test'."""
    norm = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z0-9]+", " ", norm.lower()).split()
    if drop:
        words = [w for w in words if w not in drop] or words
    return sep.join(words)


def extract_search_term(url: str) -> str | None:
    """Pull the query string from a search-landing URL (``term=``/``q=`` …)."""
    qs = parse_qs(urlparse(url or "").query)
    for key in _SEARCH_PARAMS:
        if qs.get(key):
            return qs[key][0]
    return None


def acronym(text: str) -> str | None:
    """Initialism of the significant words: 'All India Vet Entrance Test' -> 'aivet'.

    Returns None for single-word names (an acronym would just be one letter).
    """
    words = [w for w in slugify(text, sep=" ").split() if w not in _STOP]
    if len(words) < 2:
        return None
    return "".join(w[0] for w in words)


def candidate_slugs(sheet_url: str, exam: str | None, *, max_slugs: int = 4) -> list[str]:
    """Ordered, deduped candidate slugs derived from the search term and exam name.

    Tries, in order of likely precision: the full slug, the acronym (sites often use
    one, e.g. 'acet'), and the noise-stripped slug ('…-entrance-test' -> '…'). The
    embedded search term is preferred over the exam name when present, since it's
    what the site's own search box was given.
    """
    seeds: list[str] = []
    term = extract_search_term(sheet_url)
    if term:
        seeds.append(term)
    if exam and exam not in seeds:
        seeds.append(exam)

    slugs: list[str] = []

    def add(value: str | None) -> None:
        if value and value not in slugs:
            slugs.append(value)

    for seed in seeds:
        add(slugify(seed))
    for seed in seeds:
        add(acronym(seed))
    for seed in seeds:
        add(slugify(seed, drop=_SLUG_NOISE))
    return slugs[:max_slugs]


def dedupe(urls: list[str]) -> list[str]:
    """Order-preserving de-duplication of a candidate URL list."""
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
