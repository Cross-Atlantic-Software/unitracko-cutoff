"""Exam catalog — the *breadth* layer (coladex-style "explore all exams").

Reads the curated source sheet (``cutoffexamsheet.xlsx``: exam name, homepage,
cutoff-page link), classifies every exam deterministically by keyword
(category / level / state / conducting body), folds in the live scrapeability
probe (``data/source_probe.csv``) and reference metadata, and persists a single
``data/catalog.parquet`` the UI browses.

This is intentionally separate from the *cutoff* dataset (opening/closing ranks):
the catalog answers "what exams exist and where do their cutoffs live", while the
adapters answer "what are the actual ranks". Build/refresh with::

    python -m cutoffs.catalog
"""
from __future__ import annotations

import html
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "cutoffexamsheet.xlsx"
# CSV mirror of the exam sheet, committed so the catalog builds with pandas core
# only (no openpyxl) — important for minimal deploy environments.
SHEET_CSV = ROOT / "cutoffexamsheet.csv"
# Richer curated sheet: per-exam cutoff status + aggregator fallback links
# (CollegeDunia/Shiksha/Careers360/CollegeDekho). CSV mirror committed for the
# same pandas-core-only reason; falls back to the xlsx if the mirror is absent.
EXTRAS_XLSX = ROOT / "EXAMlinkssheet.xlsx"
EXTRAS_CSV = ROOT / "examlinkssheet.csv"
PROBE = ROOT / "data" / "source_probe.csv"
CATALOG_PATH = ROOT / "data" / "catalog.parquet"
ENRICHMENT_PATH = Path(__file__).resolve().parent / "data" / "enrichment.json"
LINKS_PATH = Path(__file__).resolve().parent / "data" / "links.json"

# Aggregator columns surfaced as cutoff fallbacks (official links stay separate).
AGGREGATOR_COLUMNS = ["CollegeDunia", "Shiksha", "Careers360", "CollegeDekho"]

CATALOG_COLUMNS = [
    "Exam", "Acronym", "Category", "Level", "State", "Body", "Metric",
    "Homepage", "CutoffURL", "CutoffStatus", "DataFormat", "Scrapeable",
    "Applicants", "Seats", "Notes", *AGGREGATOR_COLUMNS,
]

# --------------------------------------------------------------------------
# Category taxonomy — ordered; FIRST matching pattern wins, so put the more
# specific disciplines before the generic "Engineering"/"University" buckets.
# --------------------------------------------------------------------------
_CATEGORY_RULES: list[tuple[str, str]] = [
    # Multi-stream combined state CETs (engineering + agri/pharma/medical/arch):
    # route to the dominant Engineering stream BEFORE single-discipline rules,
    # else "...Engineering and Agriculture and Pharmacy..." lands in Pharmacy.
    ("Engineering & Technology",
     r"engineering.*(agricultur|pharmac|medical|architectur)|"
     r"(agricultur|pharmac|medical|architectur).*engineering"),
    # Maritime first so "Marine Engineering" co-locates with IMU/nautical.
    ("Aviation & Maritime", r"aviation|pilot|cabin crew|air hostess|nautical|maritime|"
                            r"\bmarine\b|naval architectur|\bgds\b|"
                            r"global distribution system|air transport|uran akademi|"
                            r"rating course|flying|aircraft"),
    ("Dental", r"\bdental\b"),
    ("Nursing", r"\bnursing\b|\bnurse\b|midwifery"),
    ("Paramedical", r"paramedical|para medical|allied (health|science)"),
    ("Pharmacy", r"pharmacy|pharma\b"),
    ("Veterinary", r"veterinary|\bvet\b"),
    ("Medical", r"medical|mbbs|\bneet\b|eligibility cum entrance|health sciences|"
                r"neuro|mental health"),
    ("Agriculture", r"agricultur|\bagri\b|dairy|fisher|food technology|forestry|"
                    r"horticultur"),
    ("Law", r"\blaw\b|\bllb\b|\bclat\b|legal|ailet|judiciar"),
    ("Accountancy & Finance", r"chartered accountancy|cost management|company secretary|"
                              r"\bacca\b|actuarial|\bcfa\b|\bicai\b"),
    ("Hotel Management", r"hotel management|catering|hospitality|culinary"),
    ("Design", r"\bdesign\b|fashion|\bnift\b|\bnid\b|footwear"),
    ("Architecture", r"architectur|\bnata\b"),
    ("Fine & Performing Arts", r"fine arts|visual arts|chitrakala|\bkala\b|sangeet|"
                               r"\bmusic\b|school of art|college of art"),
    ("Mass Comm & Media", r"mass communication|journalism|\bmedia\b"),
    ("Social Work", r"social work"),
    ("Forensic Science", r"forensic"),
    ("Teacher Education", r"teacher eligibility|b\.?ed\b|bachelor of education|"
                          r"basic school teaching"),
    ("Vocational & ITI", r"industrial training institute|\biti\b|vocational|"
                         r"craft instructor|kaushal|\bskill\b|dual system|"
                         r"oberoi systematic"),
    ("Languages & Humanities", r"sanskrit|\byoga\b|foreign languages|pashto|persian|"
                               r"folk literature|liberal arts|bachelor of arts\b|"
                               r"\bba entrance\b"),
    ("Sciences & Research", r"science education and research|\biiser\b|\bnest\b|"
                            r"mathematical institute|science research|"
                            r"national standard examination|\bb\.?sc\b"),
    ("Polytechnic & Diploma", r"polytechnic|diploma"),
    # "disaster management" excluded from business Management; IIFT/foreign-trade in.
    ("Management", r"(?<!disaster )management|business administration|\bbba\b|\bmba\b|"
                   r"\bpgdm\b|commerce|national test for programs|foreign trade|"
                   r"international business"),
    ("Engineering & Technology", r"engineering|technolog|technical|\bjee\b|petroleum|"
                                 r"joint entrance exam|\bb\.?tech\b|\btech\b|\biit\b|"
                                 r"\bnit\b|space science"),
    ("Defence & Security", r"\braksha\b|\bpolice\b|\bdefence\b|armed forces|\bnda\b|"
                           r"military"),
    ("Multidisciplinary / University", r".*"),  # catch-all
]

# --------------------------------------------------------------------------
# Level
# --------------------------------------------------------------------------
def _classify_level(name: str) -> str:
    n = name.lower()
    # Professional accountancy/secretary stages and short courses are certifications,
    # not PG degrees (CA "Final"/CS "Executive" are exam stages, not postgraduate).
    if re.search(r"chartered accountancy|company secretary|cost management accountancy|"
                 r"\bacca\b|actuarial|\bcfa\b|certification|\biata\b|\bgds\b|"
                 r"training (programme|scheme|course)|course admission|"
                 r"programme admission", n):
        return "Certification"
    if re.search(r"polytechnic|diploma", n):
        return "Diploma"
    # PG only on unambiguous degree-context tokens — NOT bare "postgraduate", which
    # appears in institute names (e.g. "Institute of Postgraduate Medical Education").
    if re.search(r"\bpg entrance\b|postgraduate entrance|post[- ]?graduate "
                 r"(entrance|admission|programme|program|degree|diploma)|"
                 r"master of|\bm\.?tech\b|\bmba\b|\bpgdm\b", n):
        return "PG"
    return "UG"

# --------------------------------------------------------------------------
# State / UT detection
# --------------------------------------------------------------------------
_STATES: list[tuple[str, str]] = [
    ("Andhra Pradesh", r"andhra pradesh"),
    ("Arunachal Pradesh", r"arunachal"),
    ("Assam", r"\bassam\b"),
    ("Bihar", r"\bbihar\b"),
    ("Chhattisgarh", r"chhattisgarh"),
    ("Goa", r"\bgoa\b"),
    ("Gujarat", r"gujarat"),
    ("Haryana", r"haryana"),
    ("Himachal Pradesh", r"himachal"),
    ("Jammu & Kashmir", r"jammu|\bkashmir\b"),
    ("Jharkhand", r"jharkhand"),
    ("Karnataka", r"karnataka"),
    ("Kerala", r"\bkerala\b"),
    ("Ladakh", r"ladakh"),
    ("Lakshadweep", r"lakshadweep"),
    ("Madhya Pradesh", r"madhya pradesh"),
    ("Maharashtra", r"maharashtra"),
    ("Manipur", r"manipur"),
    ("Meghalaya", r"meghalaya"),
    ("Mizoram", r"mizoram"),
    ("Nagaland", r"nagaland"),
    ("Odisha", r"odisha"),
    ("Punjab", r"\bpunjab\b"),
    ("Rajasthan", r"rajasthan"),
    ("Sikkim", r"sikkim"),
    ("Tamil Nadu", r"tamil nadu"),
    ("Telangana", r"telangana"),
    ("Tripura", r"tripura"),
    ("Uttar Pradesh", r"uttar pradesh"),
    ("Uttarakhand", r"uttarakhand|uttaranchal"),
    ("West Bengal", r"west bengal"),
    ("Chandigarh", r"chandigarh"),
    ("Delhi", r"\bdelhi\b"),
    ("Puducherry", r"puducherry|pondicherry"),
    ("Dadra & Nagar Haveli", r"dadra|nagar haveli|daman"),
]
_STATE_RE = [(name, re.compile(pat, re.I)) for name, pat in _STATES]


def classify_category(name: str) -> str:
    for cat, pat in _CATEGORY_RULES:
        if re.search(pat, name, re.I):
            return cat
    return "Multidisciplinary / University"


# Institution / city hints for exams that don't name their state outright.
_INSTITUTION_STATE: list[tuple[str, str]] = [
    (r"indraprastha|ggsipu|guru gobind singh", "Delhi"),
    (r"aryabhatta knowledge|\bbihar\b|patliputra", "Bihar"),
    (r"cochin university|cusat", "Kerala"),
    (r"baba farid", "Punjab"),
    (r"savitribai phule|sayajirao|mumbai|pune|nagpur", "Maharashtra"),
]
_INSTITUTION_STATE_RE = [(s, re.compile(p, re.I)) for p, s in _INSTITUTION_STATE]


def classify_state(name: str) -> str:
    for state, rx in _STATE_RE:
        if rx.search(name):
            return state
    for state, rx in _INSTITUTION_STATE_RE:
        if rx.search(name):
            return state
    return "All India"


# --------------------------------------------------------------------------
# Scrapeability — fold the live probe buckets into a friendly status.
# --------------------------------------------------------------------------
_BUCKET_TO_STATUS = {
    "html_table_rank": ("html", "scrapeable"),
    "html_table_norank": ("html", "html (no rank table)"),
    "html_rank_notable": ("html", "html (no table)"),
    "html_other": ("html", "html (generic)"),
    "html_rank_notable ": ("html", "html (no table)"),
    "pdf": ("pdf", "pdf"),
    "js_only": ("js", "js-rendered"),
    "non_html": ("other", "non-html"),
    "no_url": ("none", "no official cutoff"),
}


def _probe_status(bucket: str) -> tuple[str, str]:
    if not bucket or bucket == "nan":
        return ("unknown", "unknown")
    if bucket.startswith("http_"):
        return ("dead", f"blocked/dead ({bucket.split('_')[1]})")
    if bucket == "error":
        return ("dead", "unreachable")
    return _BUCKET_TO_STATUS.get(bucket, ("html", bucket))


# --------------------------------------------------------------------------
# Reference metadata for marquee exams (scale of competition). Folded in by
# acronym/substring match; the enrichment workflow extends this set.
# Source: riteshprasad.in/top-competitive-entrance-exams-in-india + public NTA/
# JoSAA figures. Numbers are approximate orders of magnitude.
# --------------------------------------------------------------------------
_REFERENCE: list[tuple[str, dict]] = [
    # JEE splits into separate counselling bodies — match the specific ones first
    # so each gets its own Body (the generic "joint entrance examination" below
    # would otherwise swallow all five into one "NTA / JoSAA" label).
    ("josaa joint seat allocation", {"Body": "JoSAA", "Metric": "Rank", "Applicants": 1300000, "Seats": 57000}),
    ("csab special rounds", {"Body": "CSAB", "Metric": "Rank", "Applicants": 200000, "Seats": 30000}),
    ("csab neut", {"Body": "CSAB-NEUT", "Metric": "Rank", "Applicants": 20000, "Seats": 2000}),
    ("jac delhi joint admission", {"Body": "JAC Delhi", "Metric": "Rank", "Applicants": 90000, "Seats": 5500}),
    ("advanced iit joint admission", {"Body": "IIT (JEE Advanced)", "Metric": "Rank", "Applicants": 180000, "Seats": 17000}),
    ("joint entrance examination", {"Body": "NTA / JoSAA", "Metric": "Rank", "Applicants": 1300000, "Seats": 57000}),
    ("national eligibility cum entrance", {"Body": "NTA / MCC", "Metric": "Rank", "Applicants": 2400000, "Seats": 110000}),
    ("common law admission test", {"Body": "Consortium of NLUs", "Metric": "Rank", "Applicants": 70000, "Seats": 3000}),
    ("all india law entrance", {"Body": "NLU Delhi", "Metric": "Rank", "Applicants": 20000, "Seats": 120}),
    ("common university entrance", {"Body": "NTA", "Metric": "Score", "Applicants": 1400000, "Seats": None}),
    ("birla institute of technology and science", {"Body": "BITS Pilani", "Metric": "Score", "Applicants": 350000, "Seats": 2300}),
    ("vellore institute of technology engineering", {"Body": "VIT", "Metric": "Rank", "Applicants": 250000, "Seats": 7500}),
    ("maharashtra common entrance test", {"Body": "Maharashtra CET Cell", "Metric": "Percentile", "Applicants": 650000, "Seats": None}),
    ("karnataka common entrance test", {"Body": "Karnataka Examination Authority", "Metric": "Rank", "Applicants": 250000, "Seats": None}),
    ("west bengal joint entrance examination", {"Body": "WBJEEB", "Metric": "Rank", "Applicants": 120000, "Seats": None}),
    ("national aptitude test in architecture", {"Body": "Council of Architecture", "Metric": "Score", "Applicants": 60000, "Seats": None}),
    ("national institute of fashion technology", {"Body": "NIFT", "Metric": "Rank", "Applicants": 60000, "Seats": 6000}),
    ("national institute of design", {"Body": "NID", "Metric": "Rank", "Applicants": 60000, "Seats": 1200}),
    ("chartered accountancy", {"Body": "ICAI", "Metric": "Pass/Fail", "Applicants": 200000, "Seats": None}),
    ("company secretary", {"Body": "ICSI", "Metric": "Pass/Fail", "Applicants": 60000, "Seats": None}),
    ("symbiosis law admission", {"Body": "Symbiosis International", "Metric": "Percentile", "Applicants": 30000, "Seats": None}),
    ("national entrance screening test", {"Body": "NISER / UM-DAE CEBS", "Metric": "Rank", "Applicants": 60000, "Seats": 400}),
    ("indian institutes of science education", {"Body": "IISERs", "Metric": "Rank", "Applicants": 50000, "Seats": 1800}),
]


def _reference_for(name: str) -> dict:
    n = name.lower()
    for needle, meta in _REFERENCE:
        if needle in n:
            return meta
    return {}


# --------------------------------------------------------------------------
def _clean(text: object) -> str:
    """En-dash -> ' - ', collapse whitespace; tolerate NaN."""
    s = "" if text is None else str(text)
    if s.lower() == "nan":
        s = ""
    return re.sub(r"\s+", " ", s.replace("–", " - ").replace("—", " - ")).strip()


def _load_extras() -> pd.DataFrame:
    """Read the curated status + aggregator-links sheet (CSV mirror preferred).

    Returns a frame keyed by cleaned exam name with ``CutoffStatus`` and the four
    aggregator URL columns. Returns an empty frame if neither source exists, so
    the catalog still builds without the overlay.
    """
    cols = ["Exam", "CutoffStatus", *AGGREGATOR_COLUMNS]
    if EXTRAS_CSV.exists():
        df = pd.read_csv(EXTRAS_CSV)
    elif EXTRAS_XLSX.exists():
        df = pd.read_excel(EXTRAS_XLSX).rename(columns={
            "Exam Name": "Exam", "Status of cutoff": "CutoffStatus",
            "Collge duniya": "CollegeDunia", "Shiksha": "Shiksha",
            "Career 360": "Careers360", "collge dekho": "CollegeDekho",
        })
    else:
        return pd.DataFrame(columns=cols)

    for c in cols:
        df[c] = df[c].map(_clean) if c in df.columns else ""
    # Drop the stray duplicated header row that leaked into the source data.
    df = df[df["Exam"] != "Exam Name"]
    return df[cols].drop_duplicates("Exam")


def _apply_extras(cat: pd.DataFrame, extras: pd.DataFrame) -> pd.DataFrame:
    """Overlay cutoff status + aggregator links onto the catalog, joined by exam.

    Aggregator URLs deliberately live in their own columns, leaving the official
    ``Homepage``/``CutoffURL`` overlay (official-only policy) untouched.
    """
    cat = cat.copy()
    new = ["CutoffStatus", *AGGREGATOR_COLUMNS]
    by_exam = {str(r["Exam"]).strip(): r for r in extras.to_dict("records")}
    for col in new:
        cat[col] = [str(by_exam.get(str(e).strip(), {}).get(col, "") or "")
                    for e in cat["Exam"]]
    return cat


def build_catalog(xlsx: Path = XLSX, probe: Path = PROBE) -> pd.DataFrame:
    """Read the sheet, classify every exam, fold in probe + reference metadata.

    Prefers the committed CSV mirror (pandas core only); falls back to the xlsx
    (needs openpyxl) if the CSV is absent.
    """
    df = pd.read_csv(SHEET_CSV) if SHEET_CSV.exists() else pd.read_excel(xlsx)
    df.columns = ["Exam", "Homepage", "CutoffURL"]
    df["Exam"] = df["Exam"].map(_clean)
    df["Homepage"] = df["Homepage"].map(_clean)
    df["CutoffURL"] = df["CutoffURL"].map(_clean)

    df["Category"] = df["Exam"].map(classify_category)
    df["Level"] = df["Exam"].map(_classify_level)
    df["State"] = df["Exam"].map(classify_state)

    # Probe -> DataFormat + Scrapeable, joined on the cutoff URL.
    fmt = pd.Series("unknown", index=df.index)
    status = pd.Series("unknown", index=df.index)
    if probe.exists():
        pr = pd.read_csv(probe).drop_duplicates("url").set_index("url")
        buckets = df["CutoffURL"].map(lambda u: str(pr["bucket"].get(u, "")))
        pairs = buckets.map(_probe_status)
        fmt = pairs.map(lambda p: p[0])
        status = pairs.map(lambda p: p[1])
    df["DataFormat"] = fmt
    df["Scrapeable"] = status

    ref = df["Exam"].map(_reference_for)
    df["Body"] = ref.map(lambda d: d.get("Body", ""))
    df["Applicants"] = ref.map(lambda d: d.get("Applicants")).astype("Int64")
    df["Seats"] = ref.map(lambda d: d.get("Seats")).astype("Int64")
    df["Metric"] = ref.map(lambda d: d.get("Metric", ""))
    df["Notes"] = ""
    df["Acronym"] = ""

    # Curated cutoff status + aggregator fallback links, merged by exam name.
    df = _apply_extras(df, _load_extras())
    df = df[CATALOG_COLUMNS].sort_values(["Category", "Exam"]).reset_index(drop=True)

    # Auto-apply saved enrichment + the official-links overlay so the build is
    # reproducible end-to-end.
    if ENRICHMENT_PATH.exists():
        import json
        records = json.loads(ENRICHMENT_PATH.read_text(encoding="utf-8"))
        df = _apply_enrichment(df, records)
    if LINKS_PATH.exists():
        import json
        links = json.loads(LINKS_PATH.read_text(encoding="utf-8"))
        df = _apply_links(df, links)
    return df


def _apply_links(cat: pd.DataFrame, links: list[dict]) -> pd.DataFrame:
    """Overlay validated OFFICIAL links (homepage/cutoff) + acronym.

    ``links`` is the single source of truth for displayed URLs: every value is an
    official, live URL or an empty string. Exams absent from the overlay keep
    whatever they had. This enforces the "official links only" policy.
    """
    cat = cat.copy()
    by_exam = {str(r.get("exam", "")).strip(): r for r in links if r.get("exam")}

    def val(row, field, current):
        rec = by_exam.get(str(row["Exam"]).strip())
        if rec is None:
            return current
        return str(rec.get(field, "") or "").strip()

    cat["Homepage"] = [val(r, "homepage", r["Homepage"]) for _, r in cat.iterrows()]
    cat["CutoffURL"] = [val(r, "cutoff", r["CutoffURL"]) for _, r in cat.iterrows()]
    cat["Acronym"] = [val(r, "acronym", r["Acronym"]) for _, r in cat.iterrows()]
    return cat


def _apply_enrichment(cat: pd.DataFrame, records: list[dict]) -> pd.DataFrame:
    """Fold enrichment metadata (Body/Level/Metric/scope) into a catalog frame.

    Records join on the verbatim exam name. Existing non-empty ``Body`` is
    preserved (curated reference wins); ``Metric``/``Notes`` come from enrichment;
    ``Level`` is upgraded when the agent is more specific.
    """
    cat = cat.copy()
    by_exam = {str(r.get("exam", "")).strip(): r for r in records if r.get("exam")}

    def pick(row, field, current, *, prefer_enrich=False):
        rec = by_exam.get(str(row["Exam"]).strip())
        val = (rec or {}).get(field, "")
        val = "" if val is None else html.unescape(str(val)).strip()
        if prefer_enrich and val:
            return val
        return current if (current and str(current).strip()) else val

    cat["Body"] = [pick(r, "body", r["Body"]) for _, r in cat.iterrows()]
    cat["Level"] = [pick(r, "level", r["Level"], prefer_enrich=True) or r["Level"]
                    for _, r in cat.iterrows()]
    cat["Metric"] = [pick(r, "metric", r["Metric"], prefer_enrich=True)
                     for _, r in cat.iterrows()]
    cat["Notes"] = [pick(r, "scope", r["Notes"], prefer_enrich=True)
                    for _, r in cat.iterrows()]
    return cat


def merge_enrichment(records: list[dict], path: Path = CATALOG_PATH) -> pd.DataFrame:
    """Apply enrichment to the on-disk catalog and rewrite it."""
    cat = _apply_enrichment(load_catalog(path), records)
    cat.to_parquet(path, index=False)
    return cat


def write_catalog(path: Path = CATALOG_PATH) -> pd.DataFrame:
    df = build_catalog()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def load_catalog(path: Path = CATALOG_PATH) -> pd.DataFrame:
    if not Path(path).exists():
        return write_catalog(path)
    return pd.read_parquet(path)


if __name__ == "__main__":
    cat = write_catalog()
    print(f"Wrote {len(cat)} exams -> {CATALOG_PATH}\n")
    print("=== by Category ===")
    print(cat["Category"].value_counts().to_string())
    print("\n=== by Level ===")
    print(cat["Level"].value_counts().to_string())
    print("\n=== by Scrapeable status ===")
    print(cat["Scrapeable"].value_counts().to_string())
    print("\n=== states covered ===", cat["State"].nunique(),
          "| All-India:", (cat["State"] == "All India").sum())
