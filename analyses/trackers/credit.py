"""Eye View credit and funding tracker: spreads, funding stress and deal flow from free primary sources.

Sources (all free, no API key)
  FRED     ICE BofA option-adjusted spreads (HY, BB, CCC, IG, BBB; FRED keeps about 3 years of these),
           Chicago Fed NFCI, St. Louis Fed Financial Stress Index, 3-month AA financial CP, 3-month T-bill, IORB, EFFR
  NY Fed   SOFR with its 1st/99th percentiles, overnight reverse repo (RRP) and standing repo facility (SRF) results
  SEC      EDGAR daily form index: counts of debt and shelf prospectus filings (424B2, 424B5, FWP, S-3ASR) and
           registration withdrawals (RW), the closest free primary trace of deals launched and deals pulled

Not covered (listed under "gaps" every run, never filled in)
  CDS levels (CDX, single names): no free primary source. The CCC minus BB spread is shown as a rough tail-risk proxy.
  "Deals priced wide" (new-issue concessions vs talk): not published free. EDGAR counts show activity, not pricing.

Analysis only. Not investment advice. Context for the desk, never blended into forecasts until tested.

Usage
  python credit.py                         readout -> analyses/output/credit_latest.json
  python credit.py --desk OUT.json [--date YYYY-MM-DD]
      writes {"meta_credit": ..., "day_credit": ...} ready to store as Desk Daily meta/credit and days/<date>.credit
"""
import argparse, json, re, statistics as st
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from common import get, pctile, zscore, SEC_UA
except ImportError:  # imported as analyses.trackers.credit
    from .common import get, pctile, zscore, SEC_UA

VERSION = "credit v1.1 (2026-11-26)"
HERE = Path(__file__).resolve().parent

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
FRED = {  # id: (label, unit)
    "BAMLH0A0HYM2": ("HY OAS", "pct"), "BAMLH0A1HYBB": ("BB OAS", "pct"), "BAMLH0A3HYC": ("CCC OAS", "pct"),
    "BAMLC0A0CM": ("IG OAS", "pct"), "BAMLC0A4CBBB": ("BBB OAS", "pct"),
    "NFCI": ("Chicago Fed NFCI", "index"), "STLFSI4": ("St. Louis Fed stress index", "index"),
    "DCPF3M": ("3m AA financial CP", "pct"), "DTB3": ("3m T-bill", "pct"), "IORB": ("IORB", "pct"), "EFFR": ("EFFR", "pct"),
}
SPREADS = ("BAMLH0A0HYM2", "BAMLH0A1HYBB", "BAMLH0A3HYC", "BAMLC0A0CM", "BAMLC0A4CBBB")
NYF = "https://markets.newyorkfed.org/api"
SEC_IDX = "https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/form.{d}.idx"
SEC_FORMS = ("424B2", "424B5", "FWP", "S-3ASR", "RW")


# ---------------------------------------------------------------- FRED
def fred(sid, start=None):
    url = FRED_CSV.format(sid) + (f"&cosd={start}" if start else "")
    rows = []
    for line in get(url).splitlines()[1:]:
        d, _, v = line.partition(",")
        try: rows.append((d, float(v)))
        except ValueError: pass  # FRED writes "." for missing days
    if not rows: raise ValueError(f"no data for {sid}")
    return rows


def describe(rows, unit, as_of=None):
    """Latest value, 5- and 20-observation changes, 3-year percentile and z-score. Spread changes in basis points."""
    if as_of: rows = [r for r in rows if r[0] <= as_of]
    vals = [v for _, v in rows]
    last = vals[-1]
    mult = 100 if unit == "pct" else 1
    ch = lambda n: round((last - vals[-1 - n]) * mult, 1) if len(vals) > n else None
    hist = vals[-756:]  # about 3 years of daily observations (weekly series: all of what FRED returns)
    return {"as_of": rows[-1][0], "last": last, "chg_5": ch(5), "chg_20": ch(20), "pctile_3y": pctile(last, hist),
            "z_3y": zscore(last, hist), "min_3y": min(hist), "max_3y": max(hist), "chg_unit": "bp" if unit == "pct" else "index pts"}


def spreads_block(as_of=None):
    out, raw = {}, {}
    for sid, (label, unit) in FRED.items():
        try:
            raw[sid] = fred(sid)
            out[sid] = {"label": label, **describe(raw[sid], unit, as_of)}
        except Exception as e:
            out[sid] = {"label": label, "error": f"{type(e).__name__}: {e}"}
    # CCC minus BB: how much extra the weakest credits pay. Rough tail proxy while CDS is missing.
    for name, a, b in (("CCC minus BB", "BAMLH0A3HYC", "BAMLH0A1HYBB"), ("CP minus T-bill", "DCPF3M", "DTB3")):
        if a in raw and b in raw:
            bd = dict(raw[b])
            pair = [(d, v - bd[d]) for d, v in raw[a] if d in bd]
            if pair: out[name] = {"label": name, "derived_from": [a, b], **describe(pair, "pct", as_of)}
    return out


# ---------------------------------------------------------------- NY Fed funding
def funding(iorb=None):
    s = json.loads(get(f"{NYF}/rates/secured/sofr/last/20.json"))["refRates"]
    s = sorted(s, key=lambda r: r["effectiveDate"])
    last = s[-1]
    out = {"sofr": {"as_of": last["effectiveDate"], "rate": last["percentRate"], "p1": last.get("percentPercentile1"),
                    "p99": last.get("percentPercentile99"), "volume_bn": last.get("volumeInBillions"),
                    "p99_minus_p1_bp": round((last["percentPercentile99"] - last["percentPercentile1"]) * 100) if last.get("percentPercentile99") is not None else None,
                    "last_20": [[r["effectiveDate"], r["percentRate"]] for r in s]}}
    if iorb is not None:
        out["sofr"]["minus_iorb_bp"] = round((last["percentRate"] - iorb) * 100)
        out["sofr"]["days_above_iorb_20"] = sum(r["percentRate"] > iorb for r in s)
    for key, path in (("rrp", "rp/reverserepo/all/results/lastTwoWeeks.json"), ("srf", "rp/repo/all/results/lastTwoWeeks.json")):
        ops = json.loads(get(f"{NYF}/{path}"))["repo"]["operations"]
        by_day = {}
        for o in ops:
            by_day[o["operationDate"]] = by_day.get(o["operationDate"], 0) + (o.get("totalAmtAccepted") or 0)
        days = sorted(by_day.items())
        out[key] = {"as_of": days[-1][0] if days else None, "last_usd": days[-1][1] if days else None,
                    "max_2w_usd": max(by_day.values()) if by_day else None, "days": days}
    return out


# ---------------------------------------------------------------- SEC EDGAR deal flow
def parse_form_idx(text):
    """Form-type daily index -> {form: [company, ...]} for the forms we track."""
    out = {f: [] for f in SEC_FORMS}
    body = text.split("-" * 20, 1)[-1]
    for line in body.splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 2 and parts[0] in out:
            out[parts[0]].append(parts[1])
    return out


def sec_index(day):
    q = (day.month - 1) // 3 + 1
    return parse_form_idx(get(SEC_IDX.format(y=day.year, q=q, d=day.strftime("%Y%m%d")), ua=SEC_UA))


def deal_flow(as_of=None, n=21, max_back=40):
    """Counts for the latest filing day plus a median of the prior 20 filing days. Days with no index (holidays) are skipped."""
    d, days = as_of or date.today(), []
    for _ in range(max_back):
        if d.weekday() < 5:
            try: days.append((d.isoformat(), sec_index(d)))
            except Exception as e:
                if "404" not in str(e) and "403" not in str(e): raise
        if len(days) >= n: break
        d -= timedelta(days=1)
    if not days: raise ValueError("no EDGAR daily index found")
    latest_day, latest = days[0]
    base = {f: [len(x[f]) for _, x in days[1:]] for f in SEC_FORMS}
    counts = {f: {"count": len(latest[f]), "median_20d": st.median(base[f]) if base[f] else None,
                  "ratio": round(len(latest[f]) / st.median(base[f]), 2) if base[f] and st.median(base[f]) else None} for f in SEC_FORMS}
    last3 = [len(x["424B5"]) for _, x in days[:3]]
    b5 = counts["424B5"]["median_20d"]
    return {"as_of": latest_day, "days_in_baseline": len(days) - 1, "counts": counts,
            "b5_3d_ratio": round(sum(last3) / (3 * b5), 2) if b5 and len(last3) == 3 else None,
            "daily": [[dd, {f: len(x[f]) for f in SEC_FORMS}] for dd, x in days],
            "withdrawals": latest["RW"][:25], "withdrawals_5d": sum(len(x["RW"]) for _, x in days[:5]),
            "note": "424B2 is mostly bank structured notes; 424B5 and S-3ASR are closer to corporate deals. RW covers equity and debt registrations."}


# ---------------------------------------------------------------- credit vs stocks divergence
DIV_WIDEN_BP, DIV_NEAR_HIGH, DIV_LOOKBACK, DIV_COOLDOWN = 40, 0.98, 60, 10


def divergence(hy=None, spx=None, as_of=None):
    """Junk-bond spreads widening while stocks sit near their highs: bond investors pulling back before stock investors.
    Fires when HY OAS is up DIV_WIDEN_BP+ over 20 observations AND the S&P 500 is within 2% of its 60-day closing high.
    Backtest over the overlap of the two FRED series: forward 5- and 20-day S&P returns after each new episode
    (fires at least DIV_COOLDOWN days apart) versus all days. Small samples: read as context, not a rule."""
    hy = hy or fred("BAMLH0A0HYM2")
    spx = spx or fred("SP500")
    if as_of: hy, spx = [r for r in hy if r[0] <= as_of], [r for r in spx if r[0] <= as_of]
    hyd = dict(hy)
    days = [(d, v) for d, v in spx if d in hyd]  # common trading days
    dates, px = [d for d, _ in days], [v for _, v in days]
    hv = [hyd[d] for d in dates]
    fire, eps, last_ep = [], [], -999
    for i in range(max(DIV_LOOKBACK, 20), len(days)):
        widen = (hv[i] - hv[i - 20]) * 100
        near = px[i] >= DIV_NEAR_HIGH * max(px[i - DIV_LOOKBACK + 1:i + 1])
        if widen >= DIV_WIDEN_BP and near:
            fire.append(i)
            if i - last_ep >= DIV_COOLDOWN: eps.append(i)
            last_ep = i
    fwd = lambda i, n: (px[i + n] / px[i] - 1) * 100 if i + n < len(px) else None

    def stats(idx, n):
        r = [x for x in (fwd(i, n) for i in idx) if x is not None]
        return {"n": len(r), "avg_pct": round(st.mean(r), 2) if r else None, "pct_down": round(100 * sum(x < 0 for x in r) / len(r)) if r else None}
    i = len(days) - 1
    hi60 = max(px[i - DIV_LOOKBACK + 1:i + 1])
    now = {"as_of": dates[i], "hy_widen_20_bp": round((hv[i] - hv[i - 20]) * 100), "spx": px[i], "spx_off_60d_high_pct": round((px[i] / hi60 - 1) * 100, 2)}
    now["firing"] = now["hy_widen_20_bp"] >= DIV_WIDEN_BP and px[i] >= DIV_NEAR_HIGH * hi60
    return {"now": now, "rule": f"HY spread +{DIV_WIDEN_BP}bp+ over 20 days while the S&P is within {round((1 - DIV_NEAR_HIGH) * 100)}% of its {DIV_LOOKBACK}-day high",
            "sample": {"from": dates[0], "to": dates[-1], "days": len(days), "fire_days": len(fire), "episodes": len(eps),
                       "episode_dates": [dates[j] for j in eps][-12:]},
            "after_episodes": {"5d": stats(eps, 5), "20d": stats(eps, 20)},
            "all_days": {"5d": stats(range(len(days)), 5), "20d": stats(range(len(days)), 20)},
            "source": [FRED_CSV.format("BAMLH0A0HYM2"), FRED_CSV.format("SP500")]}


# ---------------------------------------------------------------- flags and run
def flags(sp, fu, df):
    F = []
    g = lambda k: sp.get(k, {}) if "error" not in sp.get(k, {}) else {}
    hy, ccc, ig = g("BAMLH0A0HYM2"), g("BAMLH0A3HYC"), g("BAMLC0A0CM")
    if hy.get("chg_20") is not None and hy["chg_20"] >= 50: F.append(f"HY spread +{hy['chg_20']:.0f}bp in 20 days (to {hy['last']:.2f}%)")
    if hy.get("pctile_3y") is not None and hy["pctile_3y"] >= 90: F.append(f"HY spread at {hy['pctile_3y']}th pct of 3y range: wide")
    if hy.get("pctile_3y") is not None and hy["pctile_3y"] <= 10: F.append(f"HY spread at {hy['pctile_3y']}th pct of 3y range: tight, little cushion")
    if ccc.get("chg_20") is not None and ccc["chg_20"] >= 100: F.append(f"CCC spread +{ccc['chg_20']:.0f}bp in 20 days")
    if ig.get("chg_20") is not None and ig["chg_20"] >= 20: F.append(f"IG spread +{ig['chg_20']:.0f}bp in 20 days")
    for k in ("NFCI", "STLFSI4"):
        v = g(k)
        if v.get("last") is not None and v["last"] > 0: F.append(f"{v['label']} {v['last']:+.2f}: conditions tighter than average")
        if v.get("chg_5") is not None and abs(v["chg_5"]) >= 0.5: F.append(f"{v['label']} moved {v['chg_5']:+.2f} over 5 readings")
    s = fu.get("sofr", {})
    if s.get("minus_iorb_bp") is not None and s["minus_iorb_bp"] > 0: F.append(f"SOFR {s['minus_iorb_bp']}bp above IORB: repo funding tight")
    if (fu.get("srf", {}).get("max_2w_usd") or 0) > 1e9: F.append(f"Standing repo facility used: up to ${fu['srf']['max_2w_usd'] / 1e9:.1f}B in 2 weeks")
    c = df.get("counts", {})
    if c.get("RW", {}).get("count", 0) >= 3: F.append(f"{c['RW']['count']} registration withdrawals on {df['as_of']}")
    r5 = df.get("b5_3d_ratio")  # 3 filing days, so one quiet pre-holiday session does not trip it
    if r5 is not None and r5 < 0.4: F.append(f"424B5 prospectus filings over 3 days at {r5}x their 20-day median: issuance window looks shut")
    return F


GAPS_ALWAYS = ["CDS (CDX IG/HY, single names): no free primary source; CCC minus BB shown as a proxy",
               "Deals priced wide vs talk: not published free; EDGAR counts show activity only",
               "FRED keeps only about 3 years of ICE BofA spreads, so percentiles are 3-year, not long-run"]


def run(as_of=None):
    res = {"version": VERSION, "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
           "disclaimer": "Analysis only. Not investment advice.", "gaps": []}
    res["spreads"] = spreads_block(as_of)
    res["gaps"] += [f"FRED {k}: {v['error']}" for k, v in res["spreads"].items() if "error" in v]
    iorb = res["spreads"].get("IORB", {}).get("last")
    for key, fn in (("funding", lambda: funding(iorb)), ("deals", lambda: deal_flow(date.fromisoformat(as_of) if as_of else None))):
        try: res[key] = fn()
        except Exception as e: res[key] = {"error": f"{type(e).__name__}: {e}"}; res["gaps"].append(f"{key}: {res[key]['error']}")
    try: res["divergence"] = divergence(as_of=as_of)
    except Exception as e: res["divergence"] = {"error": f"{type(e).__name__}: {e}"}; res["gaps"].append(f"divergence: {res['divergence']['error']}")
    res["flags"] = flags(res["spreads"], res.get("funding", {}), res.get("deals", {}))
    dv = res["divergence"].get("now", {})
    if dv.get("firing"):
        a = res["divergence"]["after_episodes"]["20d"]
        res["flags"].insert(0, f"Credit vs stocks divergence: HY +{dv['hy_widen_20_bp']}bp in 20 days with the S&P {dv['spx_off_60d_high_pct']}% from its 60-day high"
                            + (f" (past episodes: S&P {a['avg_pct']:+}% avg over 20 days, down {a['pct_down']}% of the time, n={a['n']})" if a["n"] else ""))
    res["gaps"] += GAPS_ALWAYS
    res["sources"] = [FRED_CSV.format("<series>"), f"{NYF}/rates/secured/sofr", f"{NYF}/rp/...", SEC_IDX.format(y="YYYY", q="Q", d="YYYYMMDD")]
    return res


def desk_docs(res, day):
    sp = {k: {x: v.get(x) for x in ("label", "as_of", "last", "chg_5", "chg_20", "pctile_3y", "z_3y")} if "error" not in v else {"error": v["error"]}
          for k, v in res["spreads"].items()}
    fu, de = res.get("funding", {}), res.get("deals", {})
    meta = {"updated": day, "version": VERSION, "spreads": sp,
            "funding": fu if "error" in fu else {"sofr": {k: v for k, v in fu["sofr"].items() if k != "last_20"},
                                                  "rrp_last_usd": fu["rrp"]["last_usd"], "srf_max_2w_usd": fu["srf"]["max_2w_usd"]},
            "deals": de, "divergence": res.get("divergence"), "flags": res["flags"], "gaps": res["gaps"], "sources": res["sources"]}
    num = lambda k: sp.get(k, {}).get("last")
    dayc = {"hy_oas": num("BAMLH0A0HYM2"), "ig_oas": num("BAMLC0A0CM"), "ccc_oas": num("BAMLH0A3HYC"),
            "spread_as_of": sp.get("BAMLH0A0HYM2", {}).get("as_of"), "nfci": num("NFCI"), "stlfsi": num("STLFSI4"),
            "sofr_minus_iorb_bp": fu.get("sofr", {}).get("minus_iorb_bp"),
            "rw_count": de.get("counts", {}).get("RW", {}).get("count"), "b5_ratio": de.get("counts", {}).get("424B5", {}).get("ratio"),
            "divergence_firing": (res.get("divergence") or {}).get("now", {}).get("firing"),
            "flags": res["flags"]}
    return {"meta_credit": meta, "day_credit": dayc}


def summary(r):
    L = [f"CREDIT AND FUNDING {r['generated_utc']} UTC (analysis only, not investment advice)"]
    for k, v in r["spreads"].items():
        if "error" in v: L.append(f"  {v['label']}: missing ({v['error']})"); continue
        derived = k in ("CCC minus BB", "CP minus T-bill")
        val = f"{v['last'] * 100:.0f}bp" if derived else (f"{v['last']:.2f}%" if FRED[k][1] == "pct" else f"{v['last']:.2f}")
        L.append(f"  {v['label']} {val} ({v['as_of']}): 5d {v['chg_5']:+} {v['chg_unit']}, 20d {v['chg_20']:+} {v['chg_unit']}, 3y percentile {v['pctile_3y']}")
    fu = r.get("funding", {})
    if "error" not in fu:
        s = fu["sofr"]
        L.append(f"  SOFR {s['rate']}% ({s['as_of']}), vs IORB {s.get('minus_iorb_bp')}bp, 1st-99th pct spread {s['p99_minus_p1_bp']}bp, volume ${s['volume_bn']}B")
        L.append(f"  RRP ${(fu['rrp']['last_usd'] or 0) / 1e9:.2f}B ({fu['rrp']['as_of']}); SRF max 2w ${(fu['srf']['max_2w_usd'] or 0) / 1e9:.2f}B")
    de = r.get("deals", {})
    if "error" not in de:
        c = de["counts"]
        L.append(f"  EDGAR {de['as_of']}: " + ", ".join(f"{f} {c[f]['count']} (median {c[f]['median_20d']})" for f in SEC_FORMS))
        if de["withdrawals"]: L.append(f"  Withdrawals: {'; '.join(de['withdrawals'][:8])}")
    dv = r.get("divergence", {})
    if "error" not in dv and dv:
        n, a, b = dv["now"], dv["after_episodes"], dv["all_days"]
        L.append(f"  Divergence ({dv['rule']}): now {'FIRING' if n['firing'] else 'off'} (HY {n['hy_widen_20_bp']:+}bp/20d, S&P {n['spx_off_60d_high_pct']}% off 60d high); "
                 f"{dv['sample']['episodes']} episodes since {dv['sample']['from']}: S&P next 20d {a['20d']['avg_pct']}% avg (down {a['20d']['pct_down']}%) vs all days {b['20d']['avg_pct']}% (down {b['20d']['pct_down']}%)")
    for f in r["flags"]: L.append(f"  FLAG: {f}")
    for g in r["gaps"]: L.append(f"  gap: {g}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "output" / "credit_latest.json"))
    ap.add_argument("--desk", help="write Desk Daily docs to this path")
    ap.add_argument("--date", default=date.today().isoformat())
    a = ap.parse_args()
    res = run()
    if a.desk: Path(a.desk).write_text(json.dumps(desk_docs(res, a.date), indent=1))
    else:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, indent=1))
    print(summary(res))


if __name__ == "__main__":
    main()
