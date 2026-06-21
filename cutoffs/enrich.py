"""Best-effort enrichment of the derived/context columns on top of raw rank data:

- ``Website``       — official homepage (from the source's ``SourceMeta``).
- ``SourceURL``     — page/PDF the data was taken from (from ``SourceMeta``).
- ``City``          — parsed best-effort from the institute name.
- ``Program``       — derived best-effort from ``Level`` + ``Branch``.
- ``CategoryGroup`` — normalized super-category (e.g. General/OBC/SC/ST/EWS) so the
  many per-body reservation vocabularies become filterable as one.

Text cleaning (de-glyph-doubling, whitespace collapse) is NOT done here anymore —
it lives in :func:`cutoffs.schema.normalize` so a normalized frame is already
clean. ``ingest`` calls :func:`enrich_frame` per source, passing its
``SourceMeta`` so link identity has a single home (the meta), not a parallel dict.
Nothing here raises on a bad row — unknown values are left as <NA>.
"""

from __future__ import annotations

import re

import pandas as pd

# Re-exported so existing callers/tests can import the cleaning helpers from here;
# they now physically live in schema (the single conformance step).
from cutoffs.schema import _clean_text, _dedouble  # noqa: F401
from cutoffs.source import SourceMeta

# --------------------------------------------------------------------------
# City — parsed best-effort from the institute name.
# --------------------------------------------------------------------------
# Generic words that are never a city; if the parsed token is one of these we
# leave City null rather than guess wrong (e.g. "Jadavpur University").
_CITY_STOP = {
    "university", "college", "institute", "institutes", "technology", "tech",
    "engineering", "science", "sciences", "polytechnic", "school", "vidyapeeth",
    "vidyalaya", "viswavidyalaya", "vishwavidyalaya", "research", "studies",
    "management", "campus", "centre", "center", "education",
}
_PINCODE_RE = re.compile(r"-?\s*\d[\d\s]*")          # pincodes / numeric codes
_PARENS_RE = re.compile(r"\(.*?\)")                  # trailing "(WB)", "(COEP)"
_LEAD_CODE_RE = re.compile(r"^\s*\d+\s*-\s*")        # "009-Govt. Polytechnic..."


def _derive_city(institute: object) -> object:
    """Best-effort city from an institute name. Returns <NA> when unsure."""
    if institute is None or pd.isna(institute):
        return pd.NA
    name = _dedouble(str(institute).strip())
    if not name:
        return pd.NA
    name = _LEAD_CODE_RE.sub("", name)
    has_comma = "," in name
    seg = name.rsplit(",", 1)[-1] if has_comma else name
    seg = _PARENS_RE.sub(" ", seg)
    seg = _PINCODE_RE.sub(" ", seg)
    seg = re.sub(r"\s+", " ", seg).strip(" -.&")
    if not seg:
        return pd.NA
    if has_comma:
        # The last comma segment is almost always the locality.
        return seg.title()
    # No comma: only trust the trailing token if it looks like a place name.
    last = seg.split()[-1]
    if last.lower() in _CITY_STOP or not last[:1].isalpha():
        return pd.NA
    return last.title()


# --------------------------------------------------------------------------
# Program — derived best-effort from Level + Branch.
# --------------------------------------------------------------------------
def _derive_program(level: object, branch: object) -> object:
    """Best-effort degree programme from the level and branch text."""
    lvl = "" if level is None or pd.isna(level) else str(level)
    b = "" if branch is None or pd.isna(branch) else str(branch).lower()
    pg = lvl.upper() == "PG"

    if re.search(r"b\.?\s*arch|m\.?\s*arch|architectur", b):
        return "M.Arch" if pg else "B.Arch"
    if re.search(r"pharm", b):
        return "M.Pharm" if pg else "B.Pharm"
    if re.search(r"nursing|midwifery", b):
        return "B.Sc Nursing"
    if re.search(r"veterin|b\.?\s*v\.?\s*sc", b):
        return "B.V.Sc"
    for code, deg in (("bams", "BAMS"), ("bhms", "BHMS"), ("bsms", "BSMS"),
                      ("bums", "BUMS"), ("mbbs", "MBBS"), ("\\bbds\\b", "BDS")):
        if re.search(code, b):
            return deg
    if re.search(r"agricultur|horticultur|forestry|fisher|dairy|sericultur|"
                 r"food (technolog|nutrition)|community science|natural farming", b):
        return "B.Sc (Agriculture & allied)"
    if re.search(r"b\.?\s*tech", b):
        return "B.Tech"
    if re.search(r"b\.?\s*sc", b):
        return "B.Sc"
    if lvl.title() == "Diploma":
        return "Diploma"
    if lvl.title() == "Certification":
        return "Certification"
    if pg:
        return "M.Tech"
    return "B.E./B.Tech"


# --------------------------------------------------------------------------
# CategoryGroup — normalize the many per-body reservation vocabularies into a
# small, filterable set. Best-effort: unmapped community codes fall to "Other",
# blank/unknown to "Unspecified". Order matters (most specific first).
# --------------------------------------------------------------------------
def _category_group(category: object) -> str:
    """Map a published category token onto a normalized super-category."""
    if category is None or pd.isna(category):
        return "Unspecified"
    c = str(category).strip().upper()
    if not c or c in {"UNSPECIFIED", "UNKNOWN", "NA", "N/A", "-"}:
        return "Unspecified"
    if "EWS" in c or c in {"EW", "E-UR", "EUR"}:
        return "EWS"
    if c == "SC" or "SCHEDULED CASTE" in c:
        return "SC"
    if c == "ST" or "SCHEDULED TRIBE" in c:
        return "ST"
    if ("OBC" in c or "BACKWARD" in c or "SEBC" in c
            or c in {"BC", "MBC", "BCA", "BCB", "BCM", "EZ", "MU"}):
        return "OBC"
    if ("GENERAL" in c or "OPEN" in c
            or c in {"UR", "GM", "GEN", "OP", "SM", "UNRESERVED"}):
        return "General"
    if "PWD" in c or c in {"PH", "PD", "DV"}:
        return "PwD"
    # Karnataka (KCET) reservation codes: base GM/SC/ST/1/2A/2B/3A/3B with an
    # optional region/medium suffix (G/K/R or H/KH/RH). Anchored so it can't catch
    # ordinary words like "STATE".
    km = re.match(r"^(GM|SC|ST|1|2A|2B|3A|3B)(?:G|K|R|H|KH|RH)?$", c)
    if km:
        base = km.group(1)
        return {"GM": "General", "SC": "SC", "ST": "ST"}.get(base, "OBC")
    # Maharashtra (MHT-CET) CAP seat codes, e.g. GOPENS / LSCS / GSTS / GOBCS /
    # GVJS / GNT1S / DEFOBCS / TFWS, with a Home/Other/State seat suffix (H/O/S),
    # so GSCH / GSCO / GSCS all map alike. Classify by the reservation token they
    # carry. Runs after the standard checks above.
    if len(c) >= 4 and c.endswith(("S", "H", "O")) and any(
            k in c for k in ("OPEN", "SC", "ST", "VJ", "NT1", "NT2", "NT3",
                             "OBC", "SEBC", "TFW", "DEF")):
        if "OPEN" in c or "TFW" in c or "DEF" in c:
            return "General"
        if any(k in c for k in ("OBC", "SEBC", "VJ", "NT1", "NT2", "NT3")):
            return "OBC"
        if "SC" in c:
            return "SC"
        if "ST" in c:
            return "ST"
    # Telangana/Andhra (TS EAMCET / AP EAPCET) codes: OC, BC_A..BC_E, SC, SC_I..III,
    # ST, EWS, OC_EWS (EWS already handled above). Anchored exact tokens.
    if c == "OC":
        return "General"
    if re.fullmatch(r"BC[A-E]", c):
        return "OBC"
    if re.fullmatch(r"SCI{1,3}", c):  # SC_I / SC_II / SC_III (SC handled above)
        return "SC"
    return "Other"


# All groups, for documenting the legend in the UI.
CATEGORY_GROUPS = ["General", "OBC", "SC", "ST", "EWS", "PwD", "Other", "Unspecified"]


# --------------------------------------------------------------------------
def _fill_empty(series: pd.Series, value: object) -> pd.Series:
    """Return ``series`` with null/blank cells filled by ``value`` (no-op if blank)."""
    if not value:
        return series.astype("string")
    s = series.astype("string")
    blank = s.isna() | (s.str.strip() == "")
    return s.mask(blank, value)


def enrich_frame(df: pd.DataFrame, meta: SourceMeta | None = None) -> pd.DataFrame:
    """Return a copy of ``df`` with the derived/context columns populated.

    ``meta`` is the producing source's :class:`SourceMeta`; its ``website`` and
    ``source_url`` are the single source of truth for the two link columns. City,
    Program and CategoryGroup are derived from each row's own fields. Existing
    non-empty values are preserved. The frame is assumed already conformed via
    :func:`cutoffs.schema.normalize` (which also cleans the text).
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    if meta is not None:
        out["Website"] = _fill_empty(out["Website"], meta.website)
        out["SourceURL"] = _fill_empty(out["SourceURL"], meta.source_url)

    city = out["Institute"].map(_derive_city).astype("string")
    out["City"] = out["City"].astype("string").mask(
        out["City"].isna() | (out["City"].astype("string").str.strip() == ""), city)

    prog = pd.Series([_derive_program(lvl, br)
                      for lvl, br in zip(out["Level"], out["Branch"])],
                     index=out.index, dtype="string")
    out["Program"] = out["Program"].astype("string").mask(
        out["Program"].isna() | (out["Program"].astype("string").str.strip() == ""), prog)

    out["CategoryGroup"] = pd.Series(
        [_category_group(c) for c in out["Category"]], index=out.index, dtype="string")

    return out
