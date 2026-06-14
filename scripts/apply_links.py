"""Validate researched official links and write cutoffs/data/links.json.

Pipeline:
  1. Load the find-official-links workflow output (exam/acronym/homepage/cutoff).
  2. Load data/link_probe.csv (original links + showable flags).
  3. Re-probe every researched URL LIVE; keep only those that are reachable AND
     not an aggregator (hallucinated/wrong URLs are dropped).
  4. For all 317 exams decide final homepage/cutoff: original-if-showable, else
     researched-if-valid, else "" (official-only policy).
  5. Write cutoffs/data/links.json (the single source of truth for shown links).

Usage:  python scripts/apply_links.py path/to/workflow_result.json
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "data" / "link_probe.csv"
OUT = ROOT / "cutoffs" / "data" / "links.json"

AGGREGATORS = {
    "shiksha.com", "careers360.com", "collegedekho.com", "getmyuni.com",
    "entrancezone.com", "collegepravesh.com", "collegeforme.in", "collegedunia.com",
    "embibe.com", "mbauniverse.com", "collegesearch.in", "successcds.net",
    "aglasem.com", "jagranjosh.com", "careerindia.com", "competishun.com",
    "vedantu.com", "byjus.com", "testbook.com", "oswaalbooks.com", "adda247.com",
    "catestseries.org", "aspirantmitraa.com", "youtube.com", "facebook.com",
    "wikipedia.org", "quora.com",
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"}


def host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:  # noqa: BLE001
        return ""


def is_aggregator(url: str) -> bool:
    h = host(url)
    return any(h == a or h.endswith("." + a) for a in AGGREGATORS)


def load_records(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        if isinstance(raw.get("result"), dict):
            return raw["result"].get("records", [])
        return raw.get("records", [])
    return raw if isinstance(raw, list) else []


async def probe(urls: set[str]) -> dict[str, bool]:
    urls = {u for u in urls if str(u).lower().startswith("http")}
    sem = asyncio.Semaphore(24)
    ok: dict[str, bool] = {}

    async def one(client, u):
        async with sem:
            try:
                r = await client.get(u, headers=HEADERS, timeout=12.0,
                                     follow_redirects=True)
                ok[u] = r.status_code < 400
            except Exception:  # noqa: BLE001
                ok[u] = False

    async with httpx.AsyncClient(verify=False) as client:
        await asyncio.gather(*[one(client, u) for u in urls])
    return ok


def valid_official(url: str, live: dict[str, bool]) -> bool:
    u = str(url or "").strip()
    return bool(u.lower().startswith("http") and not is_aggregator(u) and live.get(u, False))


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    records = {str(r.get("exam", "")).strip(): r for r in load_records(Path(argv[1]))
               if r.get("exam")}
    probe_df = pd.read_csv(PROBE)

    researched = {str(r.get(f, "") or "").strip()
                  for r in records.values() for f in ("homepage", "cutoff")}
    live = asyncio.run(probe(researched))

    links = []
    n_home_fixed = n_cut_fixed = n_home_blank = n_cut_blank = n_acr = 0
    for row in probe_df.itertuples():
        exam = str(row.Exam)
        rec = records.get(exam.strip())
        # Homepage
        if bool(row.home_show):
            home = str(row.Homepage)
        elif rec and valid_official(rec.get("homepage", ""), live):
            home = str(rec["homepage"]).strip(); n_home_fixed += 1
        else:
            home = ""; n_home_blank += 1
        # Cutoff
        if bool(row.cutoff_show):
            cut = str(row.CutoffURL)
        elif rec and valid_official(rec.get("cutoff", ""), live):
            cut = str(rec["cutoff"]).strip(); n_cut_fixed += 1
        else:
            cut = ""; n_cut_blank += 1
        acr = str((rec or {}).get("acronym", "") or "").strip()
        if acr:
            n_acr += 1
        links.append({"exam": exam, "homepage": home, "cutoff": cut, "acronym": acr})

    OUT.write_text(json.dumps(links, ensure_ascii=False, indent=0), encoding="utf-8")
    shown_home = sum(1 for x in links if x["homepage"])
    shown_cut = sum(1 for x in links if x["cutoff"])
    print(f"Wrote {len(links)} link records -> {OUT}")
    print(f"Homepage: {shown_home} official shown ({n_home_fixed} newly found, {n_home_blank} blanked)")
    print(f"Cutoff:   {shown_cut} official shown ({n_cut_fixed} newly found, {n_cut_blank} blanked)")
    print(f"Acronyms: {n_acr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
