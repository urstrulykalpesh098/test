"""Eye View Canada lens: USD/CAD, Bank of Canada policy rate, Canadian yields and how they line up with the US.

Sources (all free, no API key)
  Bank of Canada Valet API   FXUSDCAD (daily average rate), V39079 (target for the overnight rate), AVG.INTWO (CORRA),
                             Government of Canada 2-, 5- and 10-year benchmark yields
  Bank of Canada events page next interest rate announcement dates (www.bankofcanada.ca/press/upcoming-events/)
  FRED                       US 2- and 10-year Treasury yields (DGS2, DGS10), WTI crude (DCOILWTICO), S&P 500 (SP500);
                             DEXCAUS as a fallback for USD/CAD if Valet is down. FRED lags 1-2 days.

Not covered (listed under "gaps" every run, never filled in)
  TSX / S&P/TSX Composite: no free primary daily source reachable from the cloud box (TMX, Yahoo, Stooq blocked;
  MarketData.app's free plan is locked to one device and is kept for option chains).
  Market-implied BoC odds (CORRA futures / OIS): not published free. The "2-year minus policy rate" read is a rough
  stand-in, not a priced probability.

Context only. Like the flows, credit and policy trackers, nothing here moves a desk probability until the Sunday
review has tested it on 20+ days. Analysis only. Not investment advice.

Usage
  python canada.py                         readout -> analyses/output/canada_latest.json
  python canada.py --desk OUT.json [--date YYYY-MM-DD]
      writes {"meta_canada": ..., "day_canada": ...} ready to store as Desk Daily meta/canada and days/<date>.canada
"""
import argparse, html, json, math, re, statistics as st
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from common import get, pctile, zscore
except ImportError:  # imported as analyses.trackers.canada
    from .common import get, pctile, zscore

VERSION = "canada v1.0 (2026-11-26)"
HERE = Path(__file__).resolve().parent

VALET = "https://www.bankofcanada.ca/valet/observations/{}/json?start_date={}"
BOC_EVENTS = "https://www.bankofcanada.ca/press/upcoming-events/"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}&cosd={}"
FRED_UA = "curl/8.5.0"  # FRED stalls on some agents; this one is known to work from the cloud box

BOC = {  # Valet id: (key, label)
    "FXUSDCAD": ("usdcad", "USD/CAD (CAD per USD)"),
    "V39079": ("policy", "BoC target overnight rate"),
    "AVG.INTWO": ("corra", "CORRA"),
    "BD.CDN.2YR.DQ.YLD": ("ca2y", "Canada 2-year"),
    "BD.CDN.5YR.DQ.YLD": ("ca5y", "Canada 5-year"),
    "BD.CDN.10YR.DQ.YLD": ("ca10y", "Canada 10-year"),
}
FRED = {"DGS2": "us2y", "DGS10": "us10y", "DCOILWTICO": "wti", "SP500": "spx"}
LEAN_BP = 25  # 2y minus policy rate beyond +/-25bp counts as the market leaning toward a move

GAPS_ALWAYS = [
    "TSX: no free primary daily source reachable (TMX, Yahoo, Stooq blocked; MarketData.app kept for option chains)",
    "BoC odds: CORRA futures / OIS pricing not free; '2y minus policy' is a rough lean, not a probability",
]
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


# ---------------------------------------------------------------- fetch
def parse_valet(text):
    """Valet JSON -> {series_id: [(date, value), ...]} sorted by date, blanks dropped."""
    out = {}
    for ob in json.loads(text).get("observations", []):
        d = ob.get("d")
        for k, v in ob.items():
            if k == "d" or not isinstance(v, dict): continue
            try: out.setdefault(k, []).append((d, float(v["v"])))
            except (KeyError, TypeError, ValueError): pass
    return {k: sorted(v) for k, v in out.items()}


def valet(ids, start):
    return parse_valet(get(VALET.format(",".join(ids), start)))


def parse_fred(text):
    rows = []
    for line in text.splitlines()[1:]:
        d, _, v = line.partition(",")
        try: rows.append((d, float(v)))
        except ValueError: pass  # "." for missing days
    return rows


def fred(sid, start):
    rows = parse_fred(get(FRED_CSV.format(sid, start), ua=FRED_UA))
    if not rows: raise ValueError(f"no data for {sid}")
    return rows


def parse_boc_events(page, today):
    """Upcoming 'Interest Rate Announcement' dates from the BoC events page (dates on or after today)."""
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " | ", page)))
    found = set()
    for m in re.finditer(rf"({MONTHS}) (\d{{1,2}}), (20\d\d)[ |]{{0,40}}Interest Rate Announcement( and Monetary Policy Report)?", text):
        d = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
        if d >= today: found.add((d.isoformat(), bool(m.group(4))))
    return [{"date": d, "with_mpr": mpr} for d, mpr in sorted(found)]


# ---------------------------------------------------------------- math
def upto(rows, as_of):
    return [r for r in rows if r[0] <= as_of] if as_of else rows


def level(rows, unit="pct"):
    """Latest value, 1/5/20-observation changes (bp for rates, % for prices), 3-year percentile and z-score."""
    vals = [v for _, v in rows]
    last = vals[-1]
    def ch(n):
        if len(vals) <= n: return None
        return round((last - vals[-1 - n]) * 100, 1) if unit == "pct" else round((last / vals[-1 - n] - 1) * 100, 2)
    hist = vals[-756:]
    return {"as_of": rows[-1][0], "last": last, "chg_1": ch(1), "chg_5": ch(5), "chg_20": ch(20),
            "chg_unit": "bp" if unit == "pct" else "%", "pctile_3y": pctile(last, hist), "z_3y": zscore(last, hist),
            "min_3y": min(hist), "max_3y": max(hist)}


def log_rets(rows):
    return [(rows[i][0], math.log(rows[i][1] / rows[i - 1][1])) for i in range(1, len(rows)) if rows[i - 1][1] > 0 and rows[i][1] > 0]


def fx_move(rows):
    """20-day USD/CAD move in standard deviations of the past year's daily moves, plus 20-day realized vol."""
    r = [x for _, x in log_rets(rows)]
    if len(r) < 60: return {}
    sd = st.pstdev(r[-252:])
    move20 = sum(r[-20:])
    return {"rv20_pct": round(st.pstdev(r[-20:]) * math.sqrt(252) * 100, 2), "rv1y_pct": round(sd * math.sqrt(252) * 100, 2),
            "move20_sigma": round(move20 / (sd * math.sqrt(20)), 2) if sd else None}


def corr(a, b, n):
    """Pearson correlation of the last n days where both series have a daily log return."""
    da, db = dict(log_rets(a)), dict(log_rets(b))
    days = sorted(set(da) & set(db))[-n:]
    if len(days) < max(20, n // 2): return None
    x, y = [da[d] for d in days], [db[d] for d in days]
    sx, sy = st.pstdev(x), st.pstdev(y)
    if not sx or not sy: return None
    mx, my = st.mean(x), st.mean(y)
    return round(sum((p - mx) * (q - my) for p, q in zip(x, y)) / (len(days) * sx * sy), 2)


def spread(a, b, lag=20):
    """a minus b on the latest common date, in bp, with the change over `lag` common dates."""
    db = dict(b)
    common = [(d, v - db[d]) for d, v in a if d in db]
    if not common: return None
    last = common[-1]
    prev = common[-1 - lag] if len(common) > lag else None
    return {"as_of": last[0], "bp": round(last[1] * 100), "chg_20_bp": round((last[1] - prev[1]) * 100) if prev else None}


def policy_history(rows):
    """Rate changes (date, new rate, change in bp) from the daily target series."""
    out = []
    for (d0, v0), (d1, v1) in zip(rows, rows[1:]):
        if abs(v1 - v0) > 1e-9: out.append({"date": d1, "rate": v1, "chg_bp": round((v1 - v0) * 100)})
    return out


def lean(bp):
    if bp is None: return None
    if bp >= LEAN_BP: return "hikes"
    if bp <= -LEAN_BP: return "cuts"
    return "hold"


# ---------------------------------------------------------------- run
def run(as_of=None, today=None):
    today = today or (date.fromisoformat(as_of) if as_of else date.today())
    start = (today - timedelta(days=3 * 366)).isoformat()
    res = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "version": VERSION,
           "note": "Context only: never moves a desk probability until tested on 20+ days. Not investment advice.",
           "levels": {}, "gaps": [], "flags": []}
    raw = {}
    try:
        for sid, rows in valet(list(BOC), start).items():
            if sid in BOC: raw[BOC[sid][0]] = upto(rows, as_of)
    except Exception as e:
        res["gaps"].append(f"Bank of Canada Valet: {type(e).__name__}: {e}")
    if not raw.get("usdcad"):
        try:
            raw["usdcad"] = upto(fred("DEXCAUS", start), as_of)
            res["gaps"].append("USD/CAD from FRED DEXCAUS (Valet unavailable; lags a few days)")
        except Exception as e:
            res["gaps"].append(f"USD/CAD fallback FRED DEXCAUS: {type(e).__name__}: {e}")
    for sid, key in FRED.items():
        try: raw[key] = upto(fred(sid, start), as_of)
        except Exception as e: res["gaps"].append(f"FRED {sid}: {type(e).__name__}: {e}")

    labels = {k: lab for k, lab in BOC.values()} | {"us2y": "US 2-year", "us10y": "US 10-year", "wti": "WTI crude"}
    for key, lab in labels.items():
        if raw.get(key):
            res["levels"][key] = {"label": lab, **level(raw[key], "price" if key in ("usdcad", "wti") else "pct")}
        elif not any(key in g for g in res["gaps"]):
            res["gaps"].append(f"{lab}: no data")

    fx = raw.get("usdcad") or []
    res["fx"] = fx_move(fx) if fx else {}
    if fx:
        res["fx"]["corr_spx_60d"] = corr(fx, raw.get("spx") or [], 60)
        res["fx"]["corr_spx_1y"] = corr(fx, raw.get("spx") or [], 252)
        res["fx"]["corr_wti_60d"] = corr(fx, raw.get("wti") or [], 60)
        res["fx"]["corr_wti_1y"] = corr(fx, raw.get("wti") or [], 252)

    pol = raw.get("policy") or []
    if pol:
        hist = policy_history(pol)
        res["boc"] = {"rate": pol[-1][1], "as_of": pol[-1][0], "changes": hist[-8:], "change_dates_note": "first business day at the new rate (announcement is the day before)", "last_change": hist[-1] if hist else None}
        if raw.get("ca2y"):
            sp = spread(raw["ca2y"], pol)
            if sp: res["boc"]["two_year_minus_policy_bp"] = sp["bp"]; res["boc"]["market_lean"] = lean(sp["bp"])
    else:
        res["boc"] = {}
    try:
        res["boc"]["next_decisions"] = parse_boc_events(get(BOC_EVENTS), today)[:3]
    except Exception as e:
        res["gaps"].append(f"BoC events page: {type(e).__name__}: {e}")

    res["spreads"] = {}
    for name, a, b in (("Canada minus US 2-year", "ca2y", "us2y"), ("Canada minus US 10-year", "ca10y", "us10y"),
                       ("Canada 10y minus 2y", "ca10y", "ca2y"), ("CORRA minus BoC target", "corra", "policy")):
        if raw.get(a) and raw.get(b):
            s = spread(raw[a], raw[b])
            if s: res["spreads"][name] = s
    res["flags"] = flags(res, today)
    res["gaps"] += GAPS_ALWAYS
    res["sources"] = [VALET.format("<series>", "<start>").split("?")[0], BOC_EVENTS, FRED_CSV.format("<series>", "<start>").split("&")[0]]
    return res


def flags(res, today):
    out = []
    lv, fx, sp, boc = res["levels"], res.get("fx", {}), res.get("spreads", {}), res.get("boc", {})
    u = lv.get("usdcad")
    if fx.get("move20_sigma") is not None and abs(fx["move20_sigma"]) >= 2:
        side = "weaker" if fx["move20_sigma"] > 0 else "stronger"
        out.append(f"CAD {side}: USD/CAD {u['chg_20']:+}% in 20 days, {fx['move20_sigma']:+} sigma vs the past year")
    if u and u["pctile_3y"] is not None and (u["pctile_3y"] >= 95 or u["pctile_3y"] <= 5):
        out.append(f"USD/CAD {u['last']} at the {u['pctile_3y']}th percentile of 3 years ({'weak' if u['pctile_3y'] >= 95 else 'strong'} CAD extreme)")
    s2 = sp.get("Canada minus US 2-year")
    if s2 and s2["chg_20_bp"] is not None and abs(s2["chg_20_bp"]) >= 25:
        out.append(f"Canada-US 2-year gap moved {s2['chg_20_bp']:+}bp in 20 days to {s2['bp']}bp (rate gap is a main USD/CAD driver)")
    lc = boc.get("last_change")
    if lc and (today - date.fromisoformat(lc["date"])).days <= 7:
        out.append(f"BoC changed its rate {lc['chg_bp']:+}bp to {lc['rate']}% on {lc['date']}")
    nd = boc.get("next_decisions") or []
    if nd and (date.fromisoformat(nd[0]["date"]) - today).days <= 5:
        out.append(f"BoC decision on {nd[0]['date']}" + (" with a Monetary Policy Report" if nd[0]["with_mpr"] else ""))
    cr = sp.get("CORRA minus BoC target")
    if cr and abs(cr["bp"]) >= 10:
        out.append(f"CORRA {cr['bp']:+}bp from the BoC target: Canadian overnight funding off target")
    return out


def desk_docs(res, day):
    lv, boc = res["levels"], res.get("boc", {})
    meta = {"updated": day, "version": VERSION, "note": res["note"],
            "levels": {k: {x: v.get(x) for x in ("label", "as_of", "last", "chg_1", "chg_5", "chg_20", "chg_unit", "pctile_3y")} for k, v in lv.items()},
            "fx": res.get("fx"), "boc": boc, "spreads": res.get("spreads"), "flags": res["flags"], "gaps": res["gaps"], "sources": res["sources"]}
    num = lambda k, f="last": lv.get(k, {}).get(f)
    sp = res.get("spreads", {})
    dayc = {"usdcad": num("usdcad"), "usdcad_as_of": num("usdcad", "as_of"), "usdcad_chg_1_pct": num("usdcad", "chg_1"),
            "usdcad_move20_sigma": res.get("fx", {}).get("move20_sigma"), "boc_rate": boc.get("rate"),
            "ca2y": num("ca2y"), "ca10y": num("ca10y"),
            "ca_us_2y_bp": (sp.get("Canada minus US 2-year") or {}).get("bp"), "ca_us_10y_bp": (sp.get("Canada minus US 10-year") or {}).get("bp"),
            "market_lean": boc.get("market_lean"), "next_boc": (boc.get("next_decisions") or [{}])[0].get("date"), "flags": res["flags"]}
    return {"meta_canada": meta, "day_canada": dayc}


def summary(r):
    L = [f"CANADA LENS {r['generated_utc']} UTC (context only, analysis only, not investment advice)"]
    for k, v in r["levels"].items():
        val = f"{v['last']:.4f}" if k == "usdcad" else (f"${v['last']:.2f}" if k == "wti" else f"{v['last']:.2f}%")
        ch = lambda x: "n/a" if x is None else f"{x:+}"
        L.append(f"  {v['label']} {val} ({v['as_of']}): 1d {ch(v['chg_1'])}{v['chg_unit']}, 20d {ch(v['chg_20'])}{v['chg_unit']}, 3y percentile {v['pctile_3y']}")
    fx = r.get("fx") or {}
    if fx:
        L.append(f"  USD/CAD 20d move {fx.get('move20_sigma')} sigma; realized vol 20d {fx.get('rv20_pct')}% vs 1y {fx.get('rv1y_pct')}%")
        L.append(f"  Correlation of daily moves, USD/CAD vs S&P: 60d {fx.get('corr_spx_60d')}, 1y {fx.get('corr_spx_1y')}; vs WTI: 60d {fx.get('corr_wti_60d')}, 1y {fx.get('corr_wti_1y')}"
                 " (negative = CAD strengthens when stocks/oil rise)")
    b = r.get("boc") or {}
    if b.get("rate") is not None:
        lc = b.get("last_change")
        L.append(f"  BoC rate {b['rate']}% ({b['as_of']})" + (f", last change {lc['chg_bp']:+}bp on {lc['date']}" if lc else "")
                 + (f"; 2y minus policy {b.get('two_year_minus_policy_bp')}bp, rough lean: {b.get('market_lean')}" if "market_lean" in b else ""))
    for d in b.get("next_decisions") or []:
        L.append(f"  Next BoC decision {d['date']}" + (" (with MPR)" if d["with_mpr"] else ""))
    for k, v in (r.get("spreads") or {}).items():
        L.append(f"  {k}: {v['bp']}bp ({v['as_of']}), 20d {v['chg_20_bp'] if v['chg_20_bp'] is not None else 'n/a'}bp")
    for f in r["flags"]: L.append(f"  FLAG: {f}")
    for g in r["gaps"]: L.append(f"  gap: {g}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "output" / "canada_latest.json"))
    ap.add_argument("--desk", help="write Desk Daily docs to this path")
    ap.add_argument("--date", default=date.today().isoformat())
    a = ap.parse_args()
    res = run(today=date.fromisoformat(a.date))
    if a.desk: Path(a.desk).write_text(json.dumps(desk_docs(res, a.date), indent=1))
    else:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, indent=1))
    print(summary(res))


if __name__ == "__main__":
    main()
