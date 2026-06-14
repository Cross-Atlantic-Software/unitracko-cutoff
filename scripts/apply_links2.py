"""Deep-link merge: combine existing links.json with the deep-research output,
re-validate every candidate live (browser-tolerant), and keep the best official
link for each exam. Rewrites cutoffs/data/links.json.

Improvements over apply_links.py:
  * Browser-tolerant validation — an OFFICIAL domain that returns 401/403/406/
    429/451/503 (anti-bot) still counts as working (a human browser reaches it);
    only 404/410/genuine 5xx/connection failures are dropped.
  * Prefers the DEEPEST official cutoff page (specific page/PDF over bare root).
  * Re-validates existing shown links too, so nothing dead survives.

Usage:  python scripts/apply_links2.py path/to/deep_workflow_result.json
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
LINKS = ROOT / "cutoffs" / "data" / "links.json"

AGGREGATORS = {
    "shiksha.com", "careers360.com", "collegedekho.com", "getmyuni.com",
    "entrancezone.com", "collegepravesh.com", "collegeforme.in", "collegedunia.com",
    "embibe.com", "mbauniverse.com", "collegesearch.in", "successcds.net",
    "aglasem.com", "jagranjosh.com", "careerindia.com", "competishun.com",
    "vedantu.com", "byjus.com", "testbook.com", "oswaalbooks.com", "adda247.com",
    "catestseries.org", "aspirantmitraa.com", "youtube.com", "facebook.com",
    "wikipedia.org", "quora.com", "instagram.com", "linkedin.com",
}
# Anti-bot / rate-limit statuses: the page exists, a browser reaches it.
BOTBLOCK = {401, 403, 406, 409, 429, 451, 503}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/pdf,*/*",
           "Accept-Language": "en-US,en;q=0.9"}


def host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:  # noqa: BLE001
        return ""


def is_aggregator(url: str) -> bool:
    h = host(url)
    return any(h == a or h.endswith("." + a) for a in AGGREGATORS)


def has_depth(url: str) -> bool:
    p = urlparse(url)
    return p.path not in ("", "/") or bool(p.query)


async def probe(urls: set[str]) -> dict[str, int | None]:
    urls = {u for u in urls if str(u).lower().startswith("http")}
    sem = asyncio.Semaphore(20)
    status: dict[str, int | None] = {}

    async def one(client, u):
        async with sem:
            for attempt in range(2):
                try:
                    r = await client.get(u, headers=HEADERS, timeout=15.0,
                                         follow_redirects=True)
                    status[u] = r.status_code
                    return
                except Exception:  # noqa: BLE001
                    status[u] = None
            # leave last status (None) on repeated failure

    async with httpx.AsyncClient(verify=False) as client:
        await asyncio.gather(*[one(client, u) for u in urls])
    return status


def valid(url: str, st: dict[str, int | None]) -> bool:
    u = str(url or "").strip()
    if not u.lower().startswith("http") or is_aggregator(u):
        return False
    code = st.get(u)
    if code is None:
        return False
    return code < 400 or code in BOTBLOCK


def first_valid(cands: list[str], st) -> str:
    for u in cands:
        if valid(u, st):
            return str(u).strip()
    return ""


def best_cutoff(cands: list[str], st) -> str:
    good = [str(u).strip() for u in cands if valid(u, st)]
    if not good:
        return ""
    # stable order already prefers the researched (deeper) candidate; now bias to depth
    good.sort(key=lambda u: 1 if has_depth(u) else 0, reverse=True)
    return good[0]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    existing = {r["exam"]: r for r in json.loads(LINKS.read_text(encoding="utf-8"))}
    raw = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    recs = raw.get("result", raw).get("records", []) if isinstance(raw, dict) else raw
    new = {str(r.get("exam", "")).strip(): r for r in recs if r.get("exam")}

    candidates: set[str] = set()
    for r in existing.values():
        candidates.update([r.get("homepage", ""), r.get("cutoff", "")])
    for r in new.values():
        candidates.update([r.get("homepage", ""), r.get("cutoff", "")])
    st = asyncio.run(probe({c for c in candidates if c}))

    out = []
    n_cut_deep = n_cut_new = n_home_new = 0
    for exam, old in existing.items():
        nr = new.get(exam.strip())
        home = first_valid([old.get("homepage", ""),
                            (nr or {}).get("homepage", "")], st)
        cut_cands = [(nr or {}).get("cutoff", ""), old.get("cutoff", "")]
        cut = best_cutoff(cut_cands, st)
        if cut and cut == (nr or {}).get("cutoff", "").strip() and cut != old.get("cutoff", ""):
            n_cut_new += 1
        if cut and has_depth(cut):
            n_cut_deep += 1
        if home and home == (nr or {}).get("homepage", "").strip() and home != old.get("homepage", ""):
            n_home_new += 1
        acr = ((nr or {}).get("acronym", "") or old.get("acronym", "") or "").strip()
        out.append({"exam": exam, "homepage": home, "cutoff": cut, "acronym": acr})

    LINKS.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    sh = sum(1 for x in out if x["homepage"])
    sc = sum(1 for x in out if x["cutoff"])
    print(f"Probed {len(st)} URLs. Wrote {len(out)} records -> {LINKS}")
    print(f"Homepages shown: {sh}  (+{n_home_new} newly recovered)")
    print(f"Cutoff pages shown: {sc}  ({n_cut_deep} are deep/specific, +{n_cut_new} newly found)")
    print(f"Acronyms: {sum(1 for x in out if x['acronym'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
