"""Streamlit frontend — Indian Admission Cutoff Aggregator (coladex-style).

Three tabs:
  1. Explore Exams      — browse all catalogued exams (category/level/state/search)
  2. Cutoff Explorer    — filter real cutoff rows + rank predictor + year trends
  3. Refresh / Scrape   — run adapters (cached/latest) or point-scrape any source

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
from cutoffs.catalog import load_catalog
from cutoffs.query import CutoffQuery, distinct_values
from cutoffs.registry import get_source
from cutoffs.storage import DEFAULT_PATH, read_parquet

PARQUET = Path(DEFAULT_PATH)

st.set_page_config(page_title="Indian Cutoff Aggregator", layout="wide")

# --- ensure the cutoff dataset exists so the explorer isn't empty on first run
if not PARQUET.exists():
    ingest.run(mode="cached", path=PARQUET)

NAMES = ingest.available()
LABELS = {n: f"{get_source(n).meta.exam}  ({n})" for n in NAMES}

st.title("🎓 Indian Admission Cutoff Aggregator")
st.caption("Browse **all 317 catalogued exams** · explore real **opening/closing "
           "ranks** · predict colleges by rank. Cutoff data is curated/scraped; "
           "refresh via adapters for the latest.")

tab_explore, tab_cutoffs, tab_refresh = st.tabs(
    ["🧭  Explore Exams", "📊  Cutoff Explorer & Rank Predictor", "🔄  Refresh / Scrape"]
)

# ===========================================================================
# TAB 1 — Explore Exams (breadth: the full catalog)
# ===========================================================================
with tab_explore:
    cat = load_catalog()
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
    total = len(read_parquet(PARQUET)) if PARQUET.exists() else 0
    st.subheader("Filter real opening/closing ranks")
    st.caption(f"Dataset on disk: **{total:,} rows** · `{PARQUET}` · "
               f"bodies: {', '.join(LABELS[n] for n in NAMES)}")

    head, reset = st.columns([4, 1])
    head.markdown("**Filters**")
    if reset.button("↺ Clear filters", width="stretch"):
        for k in ("f_body", "f_year", "f_inst", "f_branch", "f_cat", "f_round", "rank"):
            st.session_state.pop(k, None)
        st.rerun()

    c1, c2, c3 = st.columns(3)
    with c1:
        f_body = st.selectbox("Body", [""] + distinct_values("Body", PARQUET), key="f_body")
        f_year = st.selectbox("Year", [""] + distinct_values("Year", PARQUET), key="f_year")
    with c2:
        f_inst = st.selectbox("Institute", [""] + distinct_values("Institute", PARQUET), key="f_inst")
        f_branch = st.selectbox("Branch", [""] + distinct_values("Branch", PARQUET), key="f_branch")
    with c3:
        f_cat = st.selectbox("Category", [""] + distinct_values("Category", PARQUET), key="f_cat")
        f_round = st.selectbox("Round", [""] + distinct_values("Round", PARQUET), key="f_round")

    rank = st.number_input(
        "🎯 Your rank — show seats you could plausibly get (closing rank ≥ this; 0 = ignore)",
        min_value=0, value=0, step=100, key="rank",
    )

    result = (
        CutoffQuery(PARQUET)
        .where("Body", f_body).where("Year", f_year).where("Institute", f_inst)
        .where("Branch", f_branch).where("Category", f_cat).where("Round", f_round)
        .max_closing_rank(rank or None)
        .to_df()
    )

    active = {"Body": f_body, "Year": f_year, "Institute": f_inst,
              "Branch": f_branch, "Category": f_cat, "Round": f_round}
    active = {k: v for k, v in active.items() if v not in ("", None)}
    if rank:
        active["ClosingRank ≥"] = rank
    if active:
        st.caption("Active: " + " · ".join(f"{k} = {v}" for k, v in active.items()))

    if result.empty:
        st.warning(f"No rows match (dataset has {total:,}). Clear filters to see all.")
    else:
        if rank:
            st.success(f"🎯 **{len(result):,}** seats within reach at rank ≤ {rank:,}.")
        else:
            st.write(f"**{len(result):,}** of {total:,} rows match.")
        st.dataframe(result, width="stretch", hide_index=True, height=380)

    st.download_button(
        "⬇️  Download filtered (CSV)",
        data=result.to_csv(index=False).encode("utf-8"),
        file_name="cutoffs_filtered.csv", mime="text/csv", disabled=result.empty,
    )

    # --- year-over-year trend -----------------------------------------------
    st.divider()
    st.markdown("#### 📈 Year-over-year closing-rank trend")
    tcol1, tcol2, tcol3 = st.columns(3)
    insts = distinct_values("Institute", PARQUET)
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
        if not trend.empty:
            series = (trend.dropna(subset=["Year"])
                      .groupby("Year")[["OpeningRank", "ClosingRank"]].min()
                      .sort_index())
            st.line_chart(series)
            st.caption(f"{t_inst} · {t_branch} · {t_cat} — lower rank = harder to get in.")
    else:
        st.info("Pick an institute, branch and category to see its multi-year trend.")

# ===========================================================================
# TAB 3 — Refresh / Scrape
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
        cat = load_catalog()
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
