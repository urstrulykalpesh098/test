"""Eye View policy and permitting tracker: state legislatures (Texas first) and federal rulemaking, from primary sources.

Sources (all free, no API key)
  Texas Legislature Online   "Bills by filing date" report for the 90th Regular Session (prefiling opened 9 Nov 2026).
                             Every filed bill with author, last action and caption. Captions are tagged by market theme.
  Federal Register API       final and proposed rules plus presidential documents from agencies that move energy,
                             permitting and financial markets (FERC, EPA, Interior, Energy, NRC, Army Corps, SEC, CFTC, Treasury)
  Session calendar           Texas dates come from the Texas Constitution; other January legislatures are left as gaps
                             until NCSL publishes its 2027 calendar. Dates are never guessed.

Analysis only. Not investment advice. A bill being filed says nothing about whether it will pass: most do not.
Context for the desk, never blended into forecasts until tested.

Usage
  python policy.py [--prev PREV.json] [--days 10]      readout -> analyses/output/policy_latest.json
  python policy.py --desk OUT.json --prev META.json [--date YYYY-MM-DD]
      writes {"meta_policy": ..., "day_policy": ...} for Desk Daily meta/policy and days/<date>.policy.
      PREV carries the Texas filing dates already read and the tagged bills, so each run reads only new days.
"""
import argparse, html, json, re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from common import get
except ImportError:
    from .common import get

VERSION = "policy v1.0 (2026-11-26)"
HERE = Path(__file__).resolve().parent

TX_SESSION = "90R"
TX_PREFILE_START = date(2026, 11, 9)
TX_REPORT = "https://capitol.texas.gov/reports/Report.aspx?LegSess={s}&ID=filingDate&Code={d}"
TX_BILL = "https://capitol.texas.gov/BillLookup/History.aspx?LegSess={s}&Bill={b}"
FR_API = "https://www.federalregister.gov/api/v1/documents.json"

# Market themes, matched on whole words in bill captions or rule titles (case-insensitive).
THEMES = {
    "power_grid": r"electric|ercot|power grid|generation facilit|energy storage|nuclear|public utility commission",
    "data_centers": r"data cent(?:er|re)|large load|cryptocurrency mining|bitcoin mining",
    "oil_gas": r"\boil\b|natural gas|pipeline|drilling|railroad commission|flaring|injection well|produced water|petroleum",
    "water": r"\bwater\b|groundwater|aquifer|desalination",
    "property_tax": r"ad valorem|property tax|appraisal",
    "crypto_digital": r"cryptocurrenc|virtual currenc|digital asset|blockchain|bitcoin|stablecoin",
    "ai_tech": r"artificial intelligence|algorithm|social media",
    "insurance": r"insurance|insurer",
    "banking_finance": r"\bbank|financial institution|lending|loan|securities|investment|pension|retirement system",
    "esg_boycott": r"boycott|environmental, social|\besg\b|divest",
    "permitting": r"permitting|environmental review|\bnepa\b|siting|interconnection|eminent domain|(?:air|water|waste|wastewater|injection|mining|construction) (?:quality )?permit",
}
THEME_RE = {k: re.compile(v, re.I) for k, v in THEMES.items()}

FR_AGENCIES = ["federal-energy-regulatory-commission", "environmental-protection-agency", "interior-department",
               "energy-department", "nuclear-regulatory-commission", "engineers-corps", "securities-and-exchange-commission",
               "commodity-futures-trading-commission", "treasury-department", "council-on-environmental-quality"]

# January 2027 legislatures. Only dates we can source go here; everything else is a gap.
CALENDAR = [
    {"state": "Texas", "event": "90th Legislature convenes", "date": "2027-01-12",
     "source": "Tex. Const. art. III, sec. 5 (second Tuesday in January of odd-numbered years)"},
    {"state": "Texas", "event": "Unrestricted bill filing ends (60th day)", "date": "2027-03-12",
     "source": "Tex. Const. art. III, sec. 5(b); date computed from the 12 Jan start, verify on TLO"},
    {"state": "Texas", "event": "Regular session ends (140th day, sine die)", "date": "2027-05-31",
     "source": "Tex. Const. art. III, sec. 24(b); date computed from the 12 Jan start, verify on TLO"},
]
CALENDAR_GAP = "Other states' January 2027 start dates: NCSL 2027 session calendar not yet published; not filled in"


def tag(text):
    return [k for k, rx in THEME_RE.items() if rx.search(text or "")]


# ---------------------------------------------------------------- Texas
_ROW = re.compile(r'Bill=([A-Z]+\d+)">[^<]*</a></div>(.*?)(?=<div class="row">|</div>\s*</div>\s*$|\Z)', re.S)
_DATA = re.compile(r'<div class="bill-search-result-data">(.*?)</div>', re.S)


def parse_tx_report(text):
    """TLO 'Bills by filing date' report -> (reported count or None, [bill dicts])."""
    m = re.search(r"Number of Bills:\s*([\d,]+)", text)
    total = int(m.group(1).replace(",", "")) if m else None
    bills = []
    for bill, chunk in _ROW.findall(text):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in _DATA.findall(chunk)]
        cells = [c for c in cells if c and not c.startswith("Author")]
        if len(cells) < 3: continue
        author, last_action, caption = cells[0], cells[1], cells[-1]
        bills.append({"bill": bill, "author": author, "last_action": last_action, "caption": caption})
    return total, bills


def tx_day(d, session=TX_SESSION):
    total, bills = parse_tx_report(get(TX_REPORT.format(s=session, d=d.strftime("%m/%d/%Y")), timeout=90))
    return {"date": d.isoformat(), "reported": total, "parsed": len(bills), "bills": bills}


def texas(prev=None, today=None, max_days=10):
    """Read filing-date reports for days not read before (weekdays from 9 Nov). Keeps only theme-tagged bills."""
    prev = prev or {}
    today = today or date.today()
    done = set(prev.get("days_done", []))
    tagged = {b["bill"]: b for b in prev.get("tagged", [])}
    themes_of = dict(prev.get("tagged_themes", {}))  # desk docs keep only recent bills in full; every id and its themes here
    themes_of.update({k: b["themes"] for k, b in tagged.items()})
    counts = dict(prev.get("filed_by_day", {}))
    todo, d = [], TX_PREFILE_START
    while d <= today:
        # Re-read today and yesterday every run: TLO adds late filings to a day after it closes.
        if d.weekday() < 5 and (d.isoformat() not in done or (today - d).days <= 1): todo.append(d)
        d += timedelta(days=1)
    new_tagged, errors, read = [], [], []
    for d in todo[:max_days]:
        try: day = tx_day(d)
        except Exception as e: errors.append(f"Texas {d}: {type(e).__name__}: {e}"); continue
        read.append(d.isoformat())
        counts[d.isoformat()] = day["reported"] if day["reported"] is not None else day["parsed"]
        if day["reported"] is not None and day["reported"] != day["parsed"]:
            errors.append(f"Texas {d}: report says {day['reported']} bills, parsed {day['parsed']}")
        for b in day["bills"]:
            th = tag(b["caption"])
            if not th: continue
            b = {**b, "themes": th, "filed": d.isoformat(), "url": TX_BILL.format(s=TX_SESSION, b=b["bill"])}
            if b["bill"] not in themes_of: new_tagged.append(b)
            tagged[b["bill"]] = b
            themes_of[b["bill"]] = th
        done.add(d.isoformat())
    pending = [x.isoformat() for x in todo if x.isoformat() not in done]
    by_theme = {}
    for th in themes_of.values():
        for t in th: by_theme[t] = by_theme.get(t, 0) + 1
    return {"session": TX_SESSION, "first_run": not prev.get("days_done"), "days_done": sorted(done), "days_read_this_run": read, "days_pending": pending,
            "filed_by_day": dict(sorted(counts.items())), "filed_total": sum(counts.values()),
            "tagged_total": len(themes_of), "tagged_themes": dict(sorted(themes_of.items())), "by_theme": dict(sorted(by_theme.items(), key=lambda kv: -kv[1])),
            "tagged": sorted(tagged.values(), key=lambda b: (b["filed"], b["bill"])), "new_tagged": new_tagged, "errors": errors,
            "source": TX_REPORT.format(s=TX_SESSION, d="MM/DD/YYYY")}


# ---------------------------------------------------------------- Federal Register
def federal_register(days=7, today=None):
    today = today or date.today()
    since = (today - timedelta(days=days)).isoformat()
    q = [("per_page", "200"), ("order", "newest"), ("conditions[publication_date][gte]", since)]
    q += [("conditions[type][]", t) for t in ("RULE", "PRORULE", "PRESDOCU")]
    q += [("conditions[agencies][]", a) for a in FR_AGENCIES]
    q += [("fields[]", f) for f in ("title", "type", "publication_date", "agencies", "html_url", "significant", "document_number", "abstract")]
    from urllib.parse import urlencode
    data = json.loads(get(FR_API + "?" + urlencode(q)))
    docs = []
    for r in data.get("results", []):
        th = tag(f"{r.get('title', '')} {r.get('abstract') or ''}")
        docs.append({"title": r.get("title"), "type": r.get("type"), "date": r.get("publication_date"),
                     "agencies": [a.get("name") or a.get("raw_name") for a in r.get("agencies", [])],
                     "significant": r.get("significant"), "themes": th, "url": r.get("html_url")})
    by_type = {}
    for d_ in docs: by_type[d_["type"]] = by_type.get(d_["type"], 0) + 1
    return {"since": since, "count": data.get("count", len(docs)), "by_type": by_type,
            "relevant": [d_ for d_ in docs if d_["themes"] or d_["significant"]][:40], "source": FR_API}


# ---------------------------------------------------------------- flags and run
def upcoming(today=None, within=60):
    today = today or date.today()
    out = []
    for c in CALENDAR:
        n = (date.fromisoformat(c["date"]) - today).days
        if 0 <= n <= within: out.append({**c, "days_away": n})
    return out


def flags(tx, fr, up):
    F = []
    for c in up:
        if c["days_away"] <= 14: F.append(f"{c['state']}: {c['event']} in {c['days_away']} days ({c['date']})")
    nt = tx.get("new_tagged", [])
    if not tx.get("first_run", True):  # the first backfill is not news
        hot = [b for b in nt if set(b["themes"]) & {"power_grid", "data_centers", "oil_gas", "permitting", "crypto_digital"}]
        if hot: F.append(f"Texas: {len(hot)} new energy/grid/permitting/crypto bills filed, e.g. {hot[0]['bill']} ({hot[0]['caption'][:80]})")
    sig = [d for d in fr.get("relevant", []) if d.get("significant") and d["type"] in ("Rule", "Proposed Rule")]
    if sig: F.append(f"Federal Register: {len(sig)} significant rules from tracked agencies since {fr['since']}, e.g. {sig[0]['title'][:80]}")
    return F


def run(prev=None, today=None, max_days=10):
    prev = prev or {}
    res = {"version": VERSION, "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
           "disclaimer": "Analysis only. Not investment advice. Filed bills mostly do not pass.", "gaps": []}
    try: res["texas"] = texas(prev.get("texas"), today, max_days)
    except Exception as e: res["texas"] = {"error": f"{type(e).__name__}: {e}"}
    try: res["federal_register"] = federal_register(today=today)
    except Exception as e: res["federal_register"] = {"error": f"{type(e).__name__}: {e}"}
    res["calendar"] = CALENDAR
    res["upcoming"] = upcoming(today)
    for k in ("texas", "federal_register"):
        if "error" in res[k]: res["gaps"].append(f"{k}: {res[k]['error']}")
    res["gaps"] += res.get("texas", {}).get("errors", [])
    if res.get("texas", {}).get("days_pending"): res["gaps"].append(f"Texas days still to read: {len(res['texas']['days_pending'])}")
    res["gaps"] += [CALENDAR_GAP, "Other states' bills: no key-free primary feed wired yet (Open States needs a free API key)"]
    res["flags"] = flags(res.get("texas", {}), res.get("federal_register", {}), res["upcoming"])
    return res


def desk_docs(res, day):
    tx = res.get("texas", {})
    keep_tx = tx
    if "error" not in tx:  # keep the doc small: all ids, but full detail only for the 40 newest tagged bills
        keep_tx = {k: tx.get(k) for k in ("session", "days_done", "filed_by_day", "filed_total", "tagged_total", "tagged_themes", "by_theme", "source")}
        keep_tx["tagged"] = [{**b, "caption": b["caption"][:160]} for b in tx.get("tagged", [])[-40:]]
    meta = {"updated": day, "version": VERSION, "texas": keep_tx, "federal_register": res.get("federal_register"),
            "calendar": res["calendar"], "upcoming": res["upcoming"], "flags": res["flags"], "gaps": res["gaps"]}
    dayp = {"tx_new_tagged": [{k: b[k] for k in ("bill", "caption", "themes")} for b in tx.get("new_tagged", [])][:30],
            "tx_filed_total": tx.get("filed_total"), "fr_count": res.get("federal_register", {}).get("count"), "flags": res["flags"]}
    return {"meta_policy": meta, "day_policy": dayp}


def summary(r):
    L = [f"POLICY AND PERMITTING {r['generated_utc']} UTC (analysis only, not investment advice)"]
    tx = r.get("texas", {})
    if "error" not in tx:
        L.append(f"  Texas {tx['session']}: {tx['filed_total']:,} bills filed over {len(tx['filed_by_day'])} filing days; {tx['tagged_total']} match market themes")
        L.append("  by theme: " + ", ".join(f"{k} {v}" for k, v in tx["by_theme"].items()))
        for b in [b for b in tx["tagged"] if set(b["themes"]) & {"power_grid", "data_centers", "permitting", "crypto_digital"}][:12]:
            L.append(f"    {b['bill']} ({b['author']}, {b['filed']}) [{', '.join(b['themes'])}] {b['caption'][:110]}")
    fr = r.get("federal_register", {})
    if "error" not in fr:
        L.append(f"  Federal Register since {fr['since']}: {fr['count']} docs from tracked agencies {fr['by_type']}")
        for d in fr["relevant"][:10]:
            L.append(f"    {d['date']} {d['type']}{' (significant)' if d['significant'] else ''}: {d['title'][:100]} [{', '.join(d['agencies'][:2])}]")
    for c in r["upcoming"]: L.append(f"  Upcoming: {c['state']} {c['event']} {c['date']} ({c['days_away']} days)")
    for f in r["flags"]: L.append(f"  FLAG: {f}")
    for g in r["gaps"]: L.append(f"  gap: {g}")
    return "\n".join(L)


def _load_prev(path):
    if not path or not Path(path).exists(): return None
    d = json.loads(Path(path).read_text())
    d = d.get("data", d)
    return d.get("meta_policy", d)  # accepts the ArtifactData out_dir file, a --desk output, or the bare doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "output" / "policy_latest.json"))
    ap.add_argument("--desk", help="write Desk Daily docs to this path")
    ap.add_argument("--prev", help="previous policy readout or meta/policy doc as JSON")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--days", type=int, default=10, help="max Texas filing days to read this run")
    a = ap.parse_args()
    res = run(_load_prev(a.prev), date.fromisoformat(a.date), a.days)
    if a.desk: Path(a.desk).write_text(json.dumps(desk_docs(res, a.date), indent=1))
    else:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, indent=1))
    print(summary(res))


if __name__ == "__main__":
    main()
