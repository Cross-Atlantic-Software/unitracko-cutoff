"""Streamlit frontend — Indian Admission Cutoff Aggregator (coladex-style).

Five tabs:
  1. Explore Exams      — browse all catalogued exams (category/level/state/search)
  2. Cutoff Explorer    — flexible multi-filter cutoff rows + rank predictor + trends
  3. Colleges by Exam   — pick an exam, see every college that admits through it
  4. Analyze            — group-by aggregation, distributions, coverage, read-only SQL
  5. Refresh / Scrape   — run adapters (cached/latest) or point-scrape any source

Breadth (the catalog) and depth (the cutoff dataset) are decoupled: the catalog
lists every exam and where its cutoffs live; the adapters/scrapers produce the
actual opening/closing ranks. Backed by DuckDB over Parquet.

Run:  streamlit run app.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from cutoffs import ingest
from cutoffs.catalog import CATALOG_PATH, load_catalog
from cutoffs.enrich import CATEGORY_GROUPS
from cutoffs.query import (
    FILTERABLE, CutoffQuery, SQLError, colleges_for_exam, distinct_values, run_sql,
)
from cutoffs.registry import get_source
from cutoffs.storage import DEFAULT_PATH, read_parquet

PARQUET = Path(DEFAULT_PATH)

st.set_page_config(page_title="Indian Cutoff Aggregator", layout="wide")


# --- caching (C3): the dataset is reread/queried on every Streamlit rerun, so
# memoize the read-only lookups, keyed by the data file's mtime so a Refresh
# (which rewrites the Parquet) busts the cache automatically.
def _data_version() -> float:
    return PARQUET.stat().st_mtime if PARQUET.exists() else 0.0


def _catalog_version() -> float:
    return CATALOG_PATH.stat().st_mtime if CATALOG_PATH.exists() else 0.0


@st.cache_data(show_spinner=False)
def cached_distinct(column: str, _ver: float) -> list:
    return distinct_values(column, PARQUET)


@st.cache_data(show_spinner=False)
def cached_total(_ver: float) -> int:
    return len(read_parquet(PARQUET)) if PARQUET.exists() else 0


@st.cache_data(show_spinner=False)
def cached_catalog(_ver: float) -> pd.DataFrame:
    return load_catalog()


@st.cache_data(show_spinner=False)
def cached_colleges(exam: str, _ver: float) -> pd.DataFrame:
    return colleges_for_exam(exam, PARQUET)

# Shared display config for the row-level cutoff table (used by more than one tab).
CUTOFF_DISPLAY_ORDER = [
    "Exam", "Website", "Institute", "City", "State", "Program", "Branch",
    "Year", "Round", "Gender", "Quota", "OpeningRank", "ClosingRank", "SourceURL",
]
CUTOFF_COLUMN_CONFIG = {
    "Exam": st.column_config.TextColumn("Exam Name"),
    "Website": st.column_config.LinkColumn("Website", display_text="open ↗"),
    "Institute": st.column_config.TextColumn("College Name"),
    "Program": st.column_config.TextColumn("Program"),
    "Year": st.column_config.NumberColumn("Year - cutoff", format="%d"),
    "Round": st.column_config.TextColumn("Round #"),
    "OpeningRank": st.column_config.NumberColumn("Opening Rank", format="%d"),
    "ClosingRank": st.column_config.NumberColumn("Closing Rank", format="%d"),
    "SourceURL": st.column_config.LinkColumn("Data taken from", display_text="source ↗"),
}

# --- ensure the cutoff dataset exists so the explorer isn't empty on first run
if not PARQUET.exists():
    ingest.run(mode="cached", path=PARQUET)

NAMES = ingest.available()
LABELS = {n: f"{get_source(n).meta.exam}  ({n})" for n in NAMES}

st.title("🎓 Indian Admission Cutoff Aggregator")
st.caption("Browse **all 317 catalogued exams** · explore real **opening/closing "
           "ranks** · predict colleges by rank. Cutoff data is curated/scraped; "
           "refresh via adapters for the latest.")

_meta = ingest.load_meta(PARQUET)
if _meta.get("generated_at"):
    st.caption(f"🕒 Data as of **{_meta['generated_at']}** "
               f"({_meta.get('mode', '—')} · {_meta.get('rows', 0):,} rows).")

tab_explore, tab_cutoffs, tab_colleges, tab_analyze, tab_refresh = st.tabs(
    ["🧭  Explore Exams", "📊  Cutoff Explorer & Rank Predictor",
     "🏛️  Colleges by Exam", "📈  Analyze", "🔄  Refresh / Scrape"]
)

# ===========================================================================
# TAB 1 — Explore Exams (breadth: the full catalog)
# ===========================================================================
with tab_explore:
    cat = cached_catalog(_catalog_version())
    st.subheader("Explore every entrance exam")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Exams catalogued", f"{len(cat):,}")
    m2.metric("Categories", cat["Category"].nunique())
    m3.metric("States / UTs", cat["State"].nunique())
    official = cat["CutoffStatus"].isin(["Official Cutoff", "Official Merit List"]).sum()
    m4.metric("Official cutoffs / merit lists", f"{official}")

    f1, f2, f3, f4 = st.columns(4)
    cats = ["All"] + sorted(cat["Category"].dropna().unique())
    levels = ["All"] + sorted(cat["Level"].dropna().unique())
    states = ["All"] + sorted(cat["State"].dropna().unique())
    statuses = ["All"] + sorted(s for s in cat["CutoffStatus"].dropna().unique() if s)
    sel_cat = f1.selectbox("Category", cats, key="c_cat")
    sel_lvl = f2.selectbox("Level", levels, key="c_lvl")
    sel_state = f3.selectbox("State / UT", states, key="c_state")
    sel_status = f4.selectbox("Cutoff status", statuses, key="c_status")
    search = st.text_input("Search exam name", key="c_search",
                           placeholder="e.g. design, polytechnic, Kerala…")

    view = cat
    if sel_cat != "All":
        view = view[view["Category"] == sel_cat]
    if sel_lvl != "All":
        view = view[view["Level"] == sel_lvl]
    if sel_state != "All":
        view = view[view["State"] == sel_state]
    if sel_status != "All":
        view = view[view["CutoffStatus"] == sel_status]
    if search:
        view = view[view["Exam"].str.contains(search, case=False, na=False, regex=False)]

    n_home = (view["Homepage"].astype(str).str.strip() != "").sum()
    n_cut = (view["CutoffURL"].astype(str).str.strip() != "").sum()
    st.write(f"**{len(view):,}** of {len(cat):,} exams  ·  "
             f"🔗 {n_home} official homepages · {n_cut} official cutoff pages")
    st.caption("**Official** links (institution / government) come first; a blank "
               "official cutoff means none was found. The **CollegeDunia / Shiksha / "
               "Careers360 / CollegeDekho** columns are third-party aggregator "
               "fallbacks — handy for the exams with no official cutoff page.")
    st.dataframe(
        view,
        width="stretch",
        hide_index=True,
        height=460,
        column_config={
            "Homepage": st.column_config.LinkColumn("Homepage", display_text="open ↗"),
            "CutoffURL": st.column_config.LinkColumn("Cutoff page", display_text="open ↗"),
            "CutoffStatus": st.column_config.TextColumn("Cutoff status", width="small"),
            "Acronym": st.column_config.TextColumn("Acronym", width="small"),
            "Applicants": st.column_config.NumberColumn("Applicants", format="%d"),
            "Seats": st.column_config.NumberColumn("Seats", format="%d"),
            "CollegeDunia": st.column_config.LinkColumn("CollegeDunia", display_text="↗"),
            "Shiksha": st.column_config.LinkColumn("Shiksha", display_text="↗"),
            "Careers360": st.column_config.LinkColumn("Careers360", display_text="↗"),
            "CollegeDekho": st.column_config.LinkColumn("CollegeDekho", display_text="↗"),
        },
    )
    st.download_button(
        "⬇️  Download catalog (CSV)",
        data=view.to_csv(index=False).encode("utf-8"),
        file_name="exam_catalog.csv",
        mime="text/csv",
    )
    with st.expander("How to read the **Scrapeable** column"):
        st.markdown(
            "- **scrapeable** — page serves an HTML rank table httpx can parse now.\n"
            "- **pdf** — cutoffs are in a PDF (use the pdfplumber adapter).\n"
            "- **js-rendered** — table is drawn client-side (use the Playwright adapter).\n"
            "- **html (no table)** — rank links/text but no static table (often a form/PDF).\n"
            "- **blocked/dead / unreachable** — 403/404/timeout when probed.\n\n"
            "Most official portals hide cutoffs behind ASP.NET forms, PDFs, or JS — "
            "so live HTML harvest is limited. The 4 bodies on the next tab ship "
            "curated real snapshots."
        )

# ===========================================================================
# TAB 2 — Cutoff Explorer & Rank Predictor (depth: real ranks)
# ===========================================================================
with tab_cutoffs:
    ver = _data_version()
    total = cached_total(ver)
    st.subheader("Filter real opening/closing ranks")
    st.caption(f"Dataset on disk: **{total:,} rows** · `{PARQUET}` · "
               f"bodies: {', '.join(LABELS[n] for n in NAMES)}")

    # Multi-value categorical filters (column, label, key). Each is a multiselect
    # so an analyst can pick any combination ("CSE OR ECE", "Maharashtra OR
    # Karnataka"); empty = no constraint. CategoryGroup is the normalized
    # reservation bucket (so "General" matches OPEN/UR/GM/SM…).
    MULTI_FILTERS = [
        ("Body", "Body", "f_body"),
        ("Exam", "Exam Name", "f_exam"),
        ("State", "State", "f_state"),
        ("City", "City", "f_city"),
        ("Program", "Program", "f_prog"),
        ("CategoryGroup", "Category (reservation)", "f_catgrp"),
        ("Year", "Year - cutoff", "f_year"),
        ("Round", "Round #", "f_round"),
        ("Gender", "Gender", "f_gender"),
        ("Quota", "Quota", "f_quota"),
    ]
    _ALL_KEYS = [k for _, _, k in MULTI_FILTERS] + [
        "f_inst_q", "f_branch_q", "cr_lo", "cr_hi", "rank", "cols_pick", "f_yr_init"]

    head, reset = st.columns([4, 1])
    head.markdown("**Filters** — pick any combination; leave a box empty to ignore it.")
    if reset.button("↺ Clear filters", width="stretch"):
        for k in _ALL_KEYS:
            st.session_state.pop(k, None)
        st.rerun()

    chosen: dict[str, list] = {}
    cols = st.columns(4)
    for i, (col, label, key) in enumerate(MULTI_FILTERS):
        options = cached_distinct(col, ver)
        # A2: default Year to the latest cycle so cutoffs aren't blended; the
        # analyst can add more years or clear it. Applied once (not sticky-locked).
        default = []
        if col == "Year" and options and not st.session_state.get("f_yr_init"):
            default = [options[-1]]
        with cols[i % 4]:
            chosen[col] = st.multiselect(label, options, default=default, key=key)
    st.session_state["f_yr_init"] = True

    # Free-text substring search + numeric rank range.
    t1, t2, t3, t4 = st.columns(4)
    inst_q = t1.text_input("College name contains", key="f_inst_q",
                           placeholder="e.g. IIT, Government, Pune")
    branch_q = t2.text_input("Branch contains", key="f_branch_q",
                             placeholder="e.g. Computer, Civil, AI")
    cr_lo = t3.number_input("Closing rank ≥", min_value=0, value=0, step=100, key="cr_lo")
    cr_hi = t4.number_input("Closing rank ≤ (0 = no cap)", min_value=0, value=0,
                            step=100, key="cr_hi")

    rank = st.number_input(
        "🎯 Rank predictor — seats reachable at your rank (closing rank ≥ this; 0 = off)",
        min_value=0, value=0, step=100, key="rank",
    )

    with st.expander("ℹ️  What does *Category (reservation)* mean?"):
        st.caption(
            "Each body publishes its own reservation codes (OPEN/UR/GM, Kerala "
            "SM/EZ/MU, …). They're normalized into: "
            + " · ".join(f"**{g}**" for g in CATEGORY_GROUPS) + ". Pick yours so "
            "the rank predictor only counts seats in your category. *Other* = "
            "body-specific community quotas that don't map cleanly; *Unspecified* "
            "= the source published a single merit list with no category split."
        )

    q = CutoffQuery(PARQUET)
    for col, values in chosen.items():
        q = q.where_in(col, values)
    q = (q.where_contains("Institute", inst_q).where_contains("Branch", branch_q)
          .where_between("ClosingRank", cr_lo or None, cr_hi or None)
          .max_closing_rank(rank or None))
    result = q.to_df()

    # Active-filter summary.
    active = {label: ", ".join(map(str, chosen[col]))
              for col, label, _ in MULTI_FILTERS if chosen[col]}
    if inst_q:
        active["College ~"] = inst_q
    if branch_q:
        active["Branch ~"] = branch_q
    if cr_lo or cr_hi:
        active["Closing rank"] = f"{cr_lo or 0:,}–{cr_hi or '∞'}"
    if rank:
        active["Reachable at"] = f"{rank:,}"
    if active:
        st.caption("Active: " + " · ".join(f"{k} = {v}" for k, v in active.items()))

    # Column picker — let the analyst choose what to see (defaults to the full set).
    shown = st.multiselect("Columns to display", CUTOFF_DISPLAY_ORDER,
                           default=CUTOFF_DISPLAY_ORDER, key="cols_pick") \
        or CUTOFF_DISPLAY_ORDER

    if result.empty:
        st.warning(f"No rows match (dataset has {total:,}). Clear filters to see all.")
    else:
        if rank:
            st.success(f"🎯 **{len(result):,}** seats within reach at rank ≤ {rank:,}.")
        else:
            st.write(f"**{len(result):,}** of {total:,} rows match.")
        # A4: be honest when the matched body(ies) publish no opening ranks.
        if result["OpeningRank"].notna().sum() == 0 and "OpeningRank" in shown:
            st.caption("ℹ️ The selected body(ies) publish only **closing** ranks — "
                       "the Opening Rank column is blank by source, not missing data.")
        st.dataframe(
            result, width="stretch", hide_index=True, height=420,
            column_order=shown, column_config=CUTOFF_COLUMN_CONFIG,
        )

    st.download_button(
        "⬇️  Download filtered (CSV)",
        data=result.to_csv(index=False).encode("utf-8"),
        file_name="cutoffs_filtered.csv", mime="text/csv", disabled=result.empty,
    )

    # --- year-over-year trend -----------------------------------------------
    st.divider()
    st.markdown("#### 📈 Year-over-year closing-rank trend")
    tcol1, tcol2, tcol3 = st.columns(3)
    insts = cached_distinct("Institute", ver)
    t_inst = tcol1.selectbox("Institute", insts, key="t_inst")
    branches = sorted(
        CutoffQuery(PARQUET).where("Institute", t_inst).to_df()["Branch"]
        .dropna().unique()
    ) if t_inst else []
    t_branch = tcol2.selectbox("Branch", branches, key="t_branch")
    cats_for = sorted(
        CutoffQuery(PARQUET).where("Institute", t_inst).where("Branch", t_branch)
        .to_df()["Category"].dropna().unique()
    ) if (t_inst and t_branch) else []
    t_cat = tcol3.selectbox("Category", cats_for, key="t_cat")

    if t_inst and t_branch and t_cat:
        trend = (
            CutoffQuery(PARQUET).where("Institute", t_inst).where("Branch", t_branch)
            .where("Category", t_cat).to_df()
        )
        years = trend.dropna(subset=["Year"])
        # A3: a single year can't make a trend; and don't plot an all-null
        # opening-rank line (the big bodies publish only closing ranks).
        if years["Year"].nunique() < 2:
            n = years["Year"].nunique()
            st.info(f"Only {n} year of data for this selection — a year-over-year "
                    "trend needs at least 2. Try another institute/branch/category.")
        else:
            value_cols = [c for c in ("OpeningRank", "ClosingRank")
                          if years[c].notna().any()]
            series = years.groupby("Year")[value_cols].min().sort_index()
            st.line_chart(series)
            note = "" if "OpeningRank" in value_cols else " (only closing ranks published)"
            st.caption(f"{t_inst} · {t_branch} · {t_cat} — lower rank = harder "
                       f"to get in.{note}")
    else:
        st.info("Pick an institute, branch and category to see its multi-year trend.")

# ===========================================================================
# TAB 3 — Colleges by Exam (pick an exam -> every college that admits via it)
# ===========================================================================
with tab_colleges:
    st.subheader("Colleges admitting through an exam")
    st.caption("Pick an exam to see **every college** that admits through it — one "
               "row per college, with city/state, programmes, branch count and its "
               "rank envelope. Aggregated live in DuckDB.")

    exams = cached_distinct("Exam", _data_version())
    sel_exam = st.selectbox("Exam Name", [""] + exams, key="ce_exam")

    if not sel_exam:
        st.info("Select an exam above to list its colleges.")
    else:
        colleges = cached_colleges(sel_exam, _data_version())
        if colleges.empty:
            st.warning("No colleges found for this exam in the dataset.")
        else:
            # Fold the first/last year into one readable "Years" column.
            first = colleges.pop("FirstYear")
            last = colleges.pop("LastYear")
            years = [f"{a}" if a == b else f"{a}–{b}"
                     for a, b in zip(first, last)]
            colleges.insert(5, "Years", years)

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Colleges", f"{len(colleges):,}")
            m2.metric("States / UTs", colleges["State"].nunique())
            yspan = (f"{int(first.min())}–{int(last.max())}"
                     if first.notna().any() else "—")
            m3.metric("Years covered", yspan)
            m4.metric("Cutoff records", f"{int(colleges['Records'].sum()):,}")

            st.dataframe(
                colleges, width="stretch", hide_index=True, height=460,
                column_order=[
                    "College", "City", "State", "Programs", "Branches", "Years",
                    "BestOpening", "BestClosing", "WorstClosing", "Records",
                    "Website", "SourceURL",
                ],
                column_config={
                    "College": st.column_config.TextColumn("College Name", width="large"),
                    "Programs": st.column_config.TextColumn("Programmes"),
                    "Branches": st.column_config.NumberColumn("Branches", format="%d"),
                    "BestOpening": st.column_config.NumberColumn("Best opening", format="%d"),
                    "BestClosing": st.column_config.NumberColumn("Best closing", format="%d"),
                    "WorstClosing": st.column_config.NumberColumn("Worst closing", format="%d"),
                    "Records": st.column_config.NumberColumn("Records", format="%d"),
                    "Website": st.column_config.LinkColumn("Website", display_text="open ↗"),
                    "SourceURL": st.column_config.LinkColumn("Data taken from", display_text="source ↗"),
                },
            )
            st.download_button(
                "⬇️  Download colleges (CSV)",
                data=colleges.to_csv(index=False).encode("utf-8"),
                file_name=f"colleges_{sel_exam[:30].strip().replace(' ', '_')}.csv",
                mime="text/csv",
            )

            # --- drill into one college: its full branch-level cutoff rows -----
            st.divider()
            college = st.selectbox(
                "🔎 Drill into a college — see its branch-wise cutoffs (optional)",
                [""] + colleges["College"].tolist(), key="ce_college",
            )
            if college:
                rows = (CutoffQuery(PARQUET).where("Exam", sel_exam)
                        .where("Institute", college).to_df())
                st.write(f"**{len(rows):,}** cutoff rows for *{college}*.")
                st.dataframe(
                    rows, width="stretch", hide_index=True, height=360,
                    column_order=CUTOFF_DISPLAY_ORDER, column_config=CUTOFF_COLUMN_CONFIG,
                )

# ===========================================================================
# TAB 4 — Analyze (group-by aggregation, distributions, coverage, raw SQL)
# ===========================================================================
with tab_analyze:
    aver = _data_version()
    st.subheader("Analyze the cutoff dataset")
    st.caption("Aggregate, slice and inspect coverage — for the data-analyst view. "
               "All computation runs in DuckDB over the Parquet.")

    a_agg, a_dist, a_cover, a_sql = st.tabs(
        ["Σ  Group & aggregate", "📊  Distribution", "🩺  Data coverage", "🧪  SQL"]
    )

    # --- group-by aggregation ----------------------------------------------
    with a_agg:
        st.markdown("**Group the rows, then summarize ranks per group.**")
        gcol, fcol = st.columns([2, 3])
        group_by = gcol.multiselect(
            "Group by", FILTERABLE, default=["Body"], key="an_group",
            help="One row per distinct combination of these columns.")
        # Optional quick scopes so the aggregate can be narrowed.
        f_exam = fcol.multiselect("Limit to exam(s)", cached_distinct("Exam", aver),
                                  key="an_exam")
        f_cat = fcol.multiselect("Limit to category group(s)",
                                 cached_distinct("CategoryGroup", aver), key="an_cat")

        if not group_by:
            st.info("Pick at least one *Group by* column.")
        else:
            gq = (CutoffQuery(PARQUET).where_in("Exam", f_exam)
                  .where_in("CategoryGroup", f_cat))
            stats = gq.group_stats(group_by)
            if stats.empty:
                st.warning("No rows for this selection.")
            else:
                st.write(f"**{len(stats):,}** groups · "
                         f"{int(stats['Seats'].sum()):,} rows.")
                st.dataframe(
                    stats, width="stretch", hide_index=True, height=380,
                    column_config={
                        "Seats": st.column_config.NumberColumn(format="%d"),
                        "Colleges": st.column_config.NumberColumn(format="%d"),
                        "Branches": st.column_config.NumberColumn(format="%d"),
                        "BestOpening": st.column_config.NumberColumn("Best open", format="%d"),
                        "BestClosing": st.column_config.NumberColumn("Best close", format="%d"),
                        "MedianClosing": st.column_config.NumberColumn("Median close", format="%d"),
                        "AvgClosing": st.column_config.NumberColumn("Avg close", format="%d"),
                        "WorstClosing": st.column_config.NumberColumn("Worst close", format="%d"),
                    },
                )
                metric = st.selectbox(
                    "Chart metric", ["Seats", "Colleges", "MedianClosing", "BestClosing"],
                    key="an_metric")
                chart = stats.head(25).set_index(group_by[0])[metric]
                st.bar_chart(chart)
                st.download_button(
                    "⬇️  Download aggregate (CSV)",
                    data=stats.to_csv(index=False).encode("utf-8"),
                    file_name="cutoffs_aggregate.csv", mime="text/csv")

    # --- closing-rank distribution -----------------------------------------
    with a_dist:
        st.markdown("**Closing-rank distribution for a slice.**")
        d1, d2 = st.columns(2)
        d_exam = d1.selectbox("Exam", [""] + cached_distinct("Exam", aver), key="an_d_exam")
        d_cat = d2.selectbox("Category group", [""] + cached_distinct("CategoryGroup", aver),
                             key="an_d_cat")
        dq = CutoffQuery(PARQUET).where("Exam", d_exam).where("CategoryGroup", d_cat)
        ranks = dq.to_df()["ClosingRank"].dropna()
        if ranks.empty:
            st.info("No closing-rank data for this slice.")
        else:
            import numpy as np
            st.write(f"**{len(ranks):,}** seats · median **{int(ranks.median()):,}** · "
                     f"p90 **{int(ranks.quantile(0.9)):,}** · max **{int(ranks.max()):,}**.")
            counts, edges = np.histogram(ranks, bins=30)
            hist = pd.DataFrame({"count": counts},
                                index=[int(e) for e in edges[:-1]])
            hist.index.name = "closing rank ≥"
            st.bar_chart(hist)

    # --- data coverage / completeness --------------------------------------
    with a_cover:
        st.markdown("**Per-body completeness** — % of rows with a non-null value. "
                    "Tells you where the data is thin before you trust an aggregate.")
        cov_cols = ["OpeningRank", "ClosingRank", "Round", "Quota", "Gender",
                    "City", "Category"]
        cov_sql = "SELECT Body, count(*) AS Rows, " + ", ".join(
            f"round(100.0*count(\"{c}\")/count(*),0)::BIGINT AS \"{c} %\"" for c in cov_cols
        ) + " FROM cutoffs GROUP BY Body ORDER BY Rows DESC"
        try:
            cov = run_sql(cov_sql, PARQUET)
            st.dataframe(cov, width="stretch", hide_index=True)
        except SQLError as exc:
            st.error(str(exc))
        st.caption("e.g. OpeningRank is published by only a few bodies — a 0% there "
                   "means the source ships closing ranks only.")

    # --- raw SQL escape hatch ----------------------------------------------
    with a_sql:
        st.markdown("**Read-only SQL** against the dataset (exposed as table "
                    "`cutoffs`). SELECT/WITH only; a LIMIT is added if you omit one.")
        default_sql = ("SELECT Body, CategoryGroup, count(*) AS seats,\n"
                       "       median(ClosingRank) AS median_close\n"
                       "FROM cutoffs\nGROUP BY 1, 2\nORDER BY seats DESC")
        sql_text = st.text_area("Query", value=default_sql, height=160, key="an_sql")
        if st.button("▶  Run query", key="an_run"):
            try:
                out = run_sql(sql_text, PARQUET)
                st.success(f"{len(out):,} rows.")
                st.dataframe(out, width="stretch", hide_index=True, height=360)
                st.download_button("⬇️  Download (CSV)",
                                   data=out.to_csv(index=False).encode("utf-8"),
                                   file_name="sql_result.csv", mime="text/csv")
            except SQLError as exc:
                st.error(f"Rejected: {exc}")

# ===========================================================================
# TAB 5 — Refresh / Scrape
# ===========================================================================
with tab_refresh:
    st.subheader("Regenerate the cutoff dataset")
    colA, colB = st.columns(2)
    with colA:
        scope = st.radio("Bodies", ["All bodies", "Individual"], index=0, key="r_scope")
        selected = NAMES if scope == "All bodies" else st.multiselect(
            "Pick body/bodies", NAMES, default=NAMES[:1],
            format_func=lambda n: LABELS[n], key="r_sel",
        )
        mode_label = st.radio(
            "Source", ["Use cached (fast)", "Fetch latest (refresh)"], index=0,
            key="r_mode",
            help="Cached = curated snapshot. Latest = live attempt, falls back to cached.",
        )
        mode = "latest" if mode_label.startswith("Fetch") else "cached"
        if st.button("⚙️  Generate dataset", type="primary", width="stretch"):
            if not selected:
                st.warning("Select at least one body.")
            else:
                with st.spinner("Running adapters…"):
                    df = ingest.run(selected, mode=mode, path=PARQUET)
                st.success(f"Generated {len(df):,} rows from {len(selected)} body(ies).")

    with colB:
        st.markdown("**🔍 Point-scrape any catalogued source**")
        st.caption("Run the generic HTML scraper against a cutoff page. Works only "
                   "where the page serves a static rank table (most don't — see the "
                   "Explore tab's *Scrapeable* column).")
        cat = cached_catalog(_catalog_version())
        scrapeable = cat[(cat["DataFormat"] == "html")
                         & (cat["CutoffURL"].astype(str).str.strip() != "")].sort_values("Exam")
        options = scrapeable["Exam"].tolist()
        pick = st.selectbox("Catalogued exam (HTML sources)", options, key="s_pick")
        if pick:
            row = scrapeable[scrapeable["Exam"] == pick].iloc[0]
            st.caption(f"URL: {row['CutoffURL']}")
            if st.button("🕷️  Try scrape", width="stretch"):
                from cutoffs.adapters.generic import GenericHTMLSource
                src = GenericHTMLSource(pick, row["CutoffURL"], body=row["Body"],
                                        level=row["Level"], state=row["State"])
                with st.spinner("Fetching + parsing tables…"):
                    got = src.fetch_latest()
                if got.empty:
                    st.warning("No cutoff table found (data likely behind a form, "
                               "PDF, or JS). This is expected for most portals.")
                else:
                    st.success(f"Parsed {len(got):,} rows.")
                    st.dataframe(got, width="stretch", hide_index=True, height=320)
