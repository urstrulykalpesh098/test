"""Eye View flows tracker: positioning and flows from primary sources only.

Sources (all free, all primary):
  CFTC    Traders in Financial Futures, futures only (Socrata API publicreporting.cftc.gov, dataset gpe5-46if)
  FINRA   margin statistics (monthly debit balances, Excel back to 1997)
  SSGA    SPY daily NAV / shares outstanding history (navhist xlsx)
  iShares IVV product page (shares outstanding snapshot; day-over-day flow needs the previous snapshot)
  ProShares fund pages (net assets, NAV and NAV change of leveraged and inverse index ETFs)

Analysis only. Not investment advice. Every number carries its source and as-of date; anything we
could not fetch is listed under "gaps", never filled in. Standard library plus openpyxl (for the xlsx files).

Usage
  python flows.py                                  full readout -> analyses/output/flows_latest.json
  python flows.py --desk OUT.json [--prev PREV.json] [--date YYYY-MM-DD]
      desk mode for the 16:47 close run: writes {"meta_flows": ..., "day_flows": ...} ready to store
      as Desk Daily meta/flows and days/<date>.flows. PREV is the current meta/flows doc (as saved by
      ArtifactData out_dir, or just its data object) so IVV flows carry over between runs.
"""
import argparse, io, json, re, statistics as st, time, urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

VERSION = "flows v1.1 (2026-11-26)"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
HERE = Path(__file__).resolve().parent


def get(url, binary=False, timeout=40, tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
            return b if binary else b.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == tries - 1: raise
        except urllib.error.URLError:
            if i == tries - 1: raise
        time.sleep(2 * (i + 1))


def pctile(x, xs):
    xs = [v for v in xs if v is not None]
    return round(100 * sum(v <= x for v in xs) / len(xs)) if xs and x is not None else None


def zscore(x, xs):
    xs = [v for v in xs if v is not None]
    if x is None or len(xs) < 10: return None
    sd = st.pstdev(xs)
    return round((x - st.mean(xs)) / sd, 2) if sd else None


def _num(s): return float(s.replace(",", "").replace("$", ""))


def _isodate(s):
    for f in ("%Y-%m-%d", "%b %d, %Y", "%m/%d/%Y", "%d-%b-%Y"):
        try: return datetime.strptime(s.strip(), f).date().isoformat()
        except (ValueError, AttributeError): pass
    return s


def _shift(y, m, k):
    t = y * 12 + (m - 1) + k
    return f"{t // 12}-{t % 12 + 1:02d}"


# ---------------------------------------------------------------- CFTC positioning
COT_MARKETS = {  # consolidated codes fold the E-mini and micro contracts together (in E-mini equivalents)
    "S&P 500": "13874+", "Nasdaq-100": "20974+", "Russell 2000": "239742",
    "VIX": "1170E1", "10Y Treasury": "043602", "2Y Treasury": "042601",
}
COT_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"


def cot(weeks=156):
    out = {}
    for name, code in COT_MARKETS.items():
        q = urllib.parse.urlencode({"cftc_contract_market_code": code, "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": weeks})
        try:
            rows = json.loads(get(f"{COT_URL}?{q}"))
        except Exception as e:
            out[name] = {"error": f"{type(e).__name__}: {e}"}; continue
        if not rows:
            out[name] = {"error": "no rows"}; continue
        f = lambda r, k: int(float(r.get(k) or 0))

        def nets(r):
            oi = f(r, "open_interest_all") or 1
            am = f(r, "asset_mgr_positions_long") - f(r, "asset_mgr_positions_short")
            lf = f(r, "lev_money_positions_long") - f(r, "lev_money_positions_short")
            dl = f(r, "dealer_positions_long_all") - f(r, "dealer_positions_short_all")
            return {"am": am, "lf": lf, "dl": dl, "oi": oi, "am_pct": round(100 * am / oi, 1), "lf_pct": round(100 * lf / oi, 1)}
        hist = [nets(r) for r in rows]
        now, prev = hist[0], (hist[1] if len(hist) > 1 else None)
        out[name] = {
            "report_date": rows[0]["report_date_as_yyyy_mm_dd"][:10], "oi": now["oi"],
            "asset_mgr_net": now["am"], "asset_mgr_net_pct_oi": now["am_pct"],
            "asset_mgr_wow": now["am"] - prev["am"] if prev else None,
            "asset_mgr_pctile_3y": pctile(now["am_pct"], [h["am_pct"] for h in hist]),
            "lev_funds_net": now["lf"], "lev_funds_net_pct_oi": now["lf_pct"],
            "lev_funds_wow": now["lf"] - prev["lf"] if prev else None,
            "lev_funds_pctile_3y": pctile(now["lf_pct"], [h["lf_pct"] for h in hist]),
            "lev_funds_z_3y": zscore(now["lf_pct"], [h["lf_pct"] for h in hist]),
            "dealer_net": now["dl"], "weeks": len(hist),
        }
    return {"source": "CFTC Traders in Financial Futures, futures only, publicreporting.cftc.gov dataset gpe5-46if",
            "note": "Positions as of Tuesday, published Friday 3:30 pm ET (holiday weeks slip). Net = long minus short contracts. Percentiles use net as a share of open interest over the last 3 years.",
            "markets": out}


# ---------------------------------------------------------------- FINRA margin debt
FINRA_XLSX = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"
FINRA_PAGE = "https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics"


def margin():
    rows, src = [], FINRA_XLSX
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(get(FINRA_XLSX, binary=True)), read_only=True)
        for r in wb.worksheets[0].iter_rows(values_only=True):
            if r and isinstance(r[0], str) and re.match(r"\d{4}-\d{2}$", r[0]) and isinstance(r[1], (int, float)):
                rows.append((r[0], float(r[1])))
    except Exception as e:  # fall back to the 13 months shown on the HTML page
        t = re.sub(r"<[^>]+>", " ", get(FINRA_PAGE))
        mon = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
        for m in re.finditer(r"([A-Z][a-z]{2})-(\d{2})\s+([\d,]+)\s+[\d,]+\s+[\d,]+", t):
            rows.append((f"20{m.group(2)}-{mon[m.group(1)]:02d}", _num(m.group(3))))
        src = f"{FINRA_PAGE} (xlsx failed: {type(e).__name__})"
    if not rows: return {"error": "no FINRA rows"}
    d = dict(rows); months = sorted(d)
    last_m = months[-1]; y, mo = map(int, last_m.split("-")); last = d[last_m]
    m1, m12 = d.get(_shift(y, mo, -1)), d.get(_shift(y, mo, -12))
    yoy_hist = [(d[m] / d[_shift(*map(int, m.split("-")), -12)] - 1) * 100 for m in months if _shift(*map(int, m.split("-")), -12) in d]
    cur_yoy = (last / m12 - 1) * 100 if m12 else None
    peak = max(d, key=d.get)
    return {"source": src, "note": "Debit balances in customers' securities margin accounts, $ millions, month-end; published about the third week of the next month.",
            "month": last_m, "debit_musd": last,
            "mom_pct": round((last / m1 - 1) * 100, 2) if m1 else None,
            "yoy_pct": round(cur_yoy, 1) if cur_yoy is not None else None,
            "yoy_pctile": pctile(cur_yoy, yoy_hist), "yoy_pctile_since": months[12] if len(months) > 12 else None,
            "record_month": peak, "off_record_pct": round((last / d[peak] - 1) * 100, 1),
            "last_13": [[m, d[m]] for m in months[-13:]]}


# ---------------------------------------------------------------- ETF flows
SPY_XLSX = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/navhist-us-en-spy.xlsx"
IVV_PAGE = "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf"


def spy_flows():
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(get(SPY_XLSX, binary=True)), read_only=True)
    rows = []
    for r in wb.worksheets[0].iter_rows(values_only=True):
        if r and isinstance(r[0], str) and re.match(r"\d{2}-[A-Za-z]{3}-\d{4}", r[0]) and isinstance(r[2], (int, float)):
            rows.append((_isodate(r[0]), float(r[1]), float(r[2]), float(r[3])))
    rows.sort()
    fl = [(rows[i][0], (rows[i][2] - rows[i - 1][2]) * rows[i][1]) for i in range(1, len(rows))]  # $ flow = dShares x NAV
    v = [x for _, x in fl[-250:]]
    s5 = [sum(v[i - 5:i]) for i in range(5, len(v) + 1)]
    return {"source": SPY_XLSX,
            "note": "Flow = change in shares outstanding x NAV. SSGA's share count can lag creations/redemptions by a day, so read 5-day sums more firmly than single days.",
            "as_of": fl[-1][0], "aum_usd": rows[-1][3],
            "flow_1d_usd": round(fl[-1][1]), "flow_5d_usd": round(sum(v[-5:])), "flow_20d_usd": round(sum(v[-20:])),
            "flow_1d_z_1y": zscore(v[-1], v), "flow_5d_z_1y": zscore(s5[-1], s5) if s5 else None,
            "last_10": [[d, round(x)] for d, x in fl[-10:]]}


def ishares_snapshot(prev=None, url=IVV_PAGE, ticker="IVV"):
    t = get(url).replace("&quot;", '"')
    blk = re.search(r'"sharesOutstanding":\{([^}]*)\}', t)
    blk = blk.group(1) if blk else ""
    so = re.search(r'"formattedValue":"([\d,]+)"', blk)
    asof = re.search(r'"formattedAsOfDate":"([^"]+)"', blk)
    na = re.search(r'"name":"Net Assets of Fund","value":"\$([\d.,]+)"', t)
    s = {"ticker": ticker, "source": url, "shares_out": _num(so.group(1)) if so else None,
         "as_of": _isodate(asof.group(1)) if asof else None, "aum_usd": _num(na.group(1)) if na else None}
    if prev and prev.get("shares_out") and s["shares_out"] and s["aum_usd"]:
        if prev.get("as_of") != s["as_of"]:
            s["flow_usd"] = round((s["shares_out"] - prev["shares_out"]) * s["aum_usd"] / s["shares_out"])
            s["flow_since"] = prev.get("as_of")
        else:  # same snapshot as last run: carry the last computed flow forward
            for k in ("flow_usd", "flow_since"):
                if prev.get(k) is not None: s[k] = prev[k]
    return s


# ---------------------------------------------------------------- leveraged ETF rebalance
LEV_FUNDS = [("TQQQ", "Nasdaq-100", 3), ("SQQQ", "Nasdaq-100", -3), ("QLD", "Nasdaq-100", 2), ("QID", "Nasdaq-100", -2),
             ("UPRO", "S&P 500", 3), ("SPXU", "S&P 500", -3), ("SSO", "S&P 500", 2), ("SDS", "S&P 500", -2),
             ("URTY", "Russell 2000", 3), ("SRTY", "Russell 2000", -3)]
LEV_GAPS = "Direxion funds (SPXL, SPXS, TNA, TZA, SOXL, SOXS) are missing: direxion.com refuses automated requests. Single-stock leveraged ETFs are not covered."


def proshares(tk):
    url = f"https://www.proshares.com/our-etfs/leveraged-and-inverse/{tk.lower()}"
    t = get(url)
    g = lambda pat: (re.search(pat, t) or [None, None])[1]
    aum, nav = g(r'id="snapshot-netAssets"[^>]*>\$([\d,.]+)'), g(r'id="price-nav"[^>]*>\$([\d,.]+)')
    chg, asof = g(r'id="price-navChange"[^>]*>([-+$\d,.]+)'), g(r'id="price-asOfDate"[^>]*>\s*as of ([\d/]+)')
    return {"aum": _num(aum) if aum else None, "nav": _num(nav) if nav else None,
            "nav_chg": float(re.sub(r"[$,+]", "", chg)) if chg and re.search(r"\d", chg) else None,
            "as_of": _isodate(asof) if asof else None, "url": url}


def lev_rebalance():
    """Each daily-reset fund must trade L(L-1) x r x AUM_start of the index near the close, in the direction
    of the move, for bull and bear funds alike. With the fund's own NAV return R = L*r this is
    (L-1) x R x AUM_start, and AUM_start ~ AUM_end / (1+R) (ignores same-day creations)."""
    funds, per1, last = [], {}, {}
    for tk, idx, L in LEV_FUNDS:
        try: p = proshares(tk)
        except Exception as e:
            funds.append({"t": tk, "error": f"{type(e).__name__}: {e}"}); continue
        if not p["aum"]:
            funds.append({"t": tk, "error": "net assets not found"}); continue
        row = {"t": tk, "idx": idx, "L": L, "aum": p["aum"], "as_of": p["as_of"],
               "per_1pct": round(L * (L - 1) * 0.01 * p["aum"])}
        per1[idx] = per1.get(idx, 0) + row["per_1pct"]
        if p["nav"] and p["nav_chg"] is not None and p["nav"] - p["nav_chg"] > 0:
            R = p["nav_chg"] / (p["nav"] - p["nav_chg"])
            row["fund_ret_pct"] = round(100 * R, 2); row["index_ret_pct"] = round(100 * R / L, 2)
            row["flow"] = round((L - 1) * R * p["aum"] / (1 + R))
            e = last.setdefault(idx, {"flow": 0, "as_of": p["as_of"], "index_ret_pct": [], "n": 0})
            e["flow"] += row["flow"]; e["index_ret_pct"].append(row["index_ret_pct"]); e["n"] += 1
        funds.append(row)
    for idx, e in last.items():  # the index move implied by each fund should agree; report the median
        e["index_ret_pct"] = round(st.median(e["index_ret_pct"]), 2)
    return {"source": "ProShares fund pages (net assets, NAV, NAV change)",
            "formula": "flow = L(L-1) x r x AUM, summed over funds tracking the same index",
            "per_1pct_usd": per1, "last_session": last, "funds": funds}


# ---------------------------------------------------------------- flags and assembly
def flags(pos, mg, spy):
    """Mechanical attention flags. Context for the desk; they do not move probabilities (method/notes)."""
    out = []
    for n in ("S&P 500", "Nasdaq-100", "Russell 2000", "VIX"):
        m = pos.get("markets", {}).get(n, {})
        for who, k in (("Hedge funds", "lev_funds_pctile_3y"), ("Asset managers", "asset_mgr_pctile_3y")):
            p = m.get(k)
            if p is not None and (p >= 90 or p <= 10):
                out.append(f"{who} {n} futures net at {p}th percentile of 3 years ({'least short / most long' if p >= 90 else 'most short / least long'}), CFTC {m['report_date']}")
    if spy.get("flow_5d_z_1y") is not None and abs(spy["flow_5d_z_1y"]) >= 2:
        out.append(f"SPY 5-day flow {spy['flow_5d_usd'] / 1e9:+.1f}B, z {spy['flow_5d_z_1y']:+.1f} vs the last year (SSGA, to {spy['as_of']})")
    if mg.get("mom_pct") is not None and mg["mom_pct"] <= -5:
        out.append(f"Margin debt fell {mg['mom_pct']}% in {mg['month']} (FINRA): deleveraging")
    return out


def run(prev=None):
    prev = prev or {}
    res, gaps = {"version": VERSION, "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                 "disclaimer": "Analysis only. Not investment advice."}, []
    for key, fn in (("positioning", cot), ("margin_debt", margin), ("spy", spy_flows), ("lev", lev_rebalance)):
        try: res[key] = fn()
        except Exception as e: res[key] = {"error": f"{type(e).__name__}: {e}"}; gaps.append(f"{key}: {res[key]['error']}")
    try: res["ivv"] = ishares_snapshot(prev.get("ivv"))
    except Exception as e: res["ivv"] = {"error": f"{type(e).__name__}: {e}"}; gaps.append(f"ivv: {res['ivv']['error']}")
    for n, m in res.get("positioning", {}).get("markets", {}).items():
        if "error" in m: gaps.append(f"CFTC {n}: {m['error']}")
    for f in res.get("lev", {}).get("funds", []):
        if "error" in f: gaps.append(f"{f['t']}: {f['error']}")
    gaps.append(LEV_GAPS)
    if "error" not in res["ivv"] and res["ivv"].get("flow_usd") is None: gaps.append("IVV flow needs a second daily snapshot")
    res["flags"] = flags(res.get("positioning", {}), res.get("margin_debt", {}), res.get("spy", {}))
    res["gaps"] = gaps
    return res


def desk_docs(res, day):
    """Compact shapes for Desk Daily: meta/flows (latest full picture) and days/<day>.flows (what the day adds)."""
    keep = ("report_date", "asset_mgr_net", "asset_mgr_net_pct_oi", "asset_mgr_wow", "asset_mgr_pctile_3y",
            "lev_funds_net", "lev_funds_net_pct_oi", "lev_funds_wow", "lev_funds_pctile_3y")
    pos = {n: {k: m.get(k) for k in keep} for n, m in res.get("positioning", {}).get("markets", {}).items() if "error" not in m}
    mg, spy, lev, ivv = (res.get(k, {}) for k in ("margin_debt", "spy", "lev", "ivv"))
    pick = lambda d, ks: {"error": d["error"]} if "error" in d else {k: d.get(k) for k in ks}
    meta = {"updated": day, "version": VERSION, "positioning": pos, "cot_report_date": next(iter(pos.values()), {}).get("report_date"),
            "margin": pick(mg, ("month", "debit_musd", "mom_pct", "yoy_pct", "yoy_pctile", "yoy_pctile_since", "record_month", "off_record_pct", "last_13")),
            "spy": pick(spy, ("as_of", "aum_usd", "flow_1d_usd", "flow_5d_usd", "flow_20d_usd", "flow_1d_z_1y", "flow_5d_z_1y", "last_10")),
            "ivv": pick(ivv, ("as_of", "shares_out", "aum_usd", "flow_usd", "flow_since")),
            "lev": {"per_1pct_usd": lev.get("per_1pct_usd"), "last_session": lev.get("last_session"),
                    "funds": [{k: f.get(k) for k in ("t", "L", "aum", "as_of", "flow")} for f in lev.get("funds", []) if "error" not in f]},
            "flags": res["flags"], "gaps": res["gaps"],
            "sources": [res.get("positioning", {}).get("source"), FINRA_XLSX, SPY_XLSX, IVV_PAGE, "https://www.proshares.com (fund pages)"]}
    ls = lev.get("last_session") or {}
    dayf = {"lev_close_usd": {i: e["flow"] for i, e in ls.items()}, "lev_index_ret_pct": {i: e["index_ret_pct"] for i, e in ls.items()},
            "lev_as_of": next(iter(ls.values()), {}).get("as_of"), "lev_per_1pct_usd": lev.get("per_1pct_usd"),
            "spy_flow_1d_usd": spy.get("flow_1d_usd"), "spy_flow_5d_usd": spy.get("flow_5d_usd"), "spy_flow_5d_z": spy.get("flow_5d_z_1y"), "spy_as_of": spy.get("as_of"),
            "ivv_flow_usd": ivv.get("flow_usd"), "ivv_as_of": ivv.get("as_of"), "flags": res["flags"]}
    return {"meta_flows": meta, "day_flows": dayf}


def B(x): return "n/a" if x is None else f"{x / 1e9:+.2f}B"


def summary(r):
    L = [f"FLOWS READOUT {r['generated_utc']} UTC (analysis only, not investment advice)"]
    for n, m in r.get("positioning", {}).get("markets", {}).items():
        if "error" in m: L.append(f"  CFTC {n}: missing ({m['error']})"); continue
        L.append(f"  CFTC {n} ({m['report_date']}): asset mgrs {m['asset_mgr_net']:+,} ({m['asset_mgr_net_pct_oi']}% OI, {m['asset_mgr_pctile_3y']}th pct, w/w {m['asset_mgr_wow']:+,}); "
                 f"hedge funds {m['lev_funds_net']:+,} ({m['lev_funds_net_pct_oi']}% OI, {m['lev_funds_pctile_3y']}th pct, w/w {m['lev_funds_wow']:+,})")
    g = r.get("margin_debt", {})
    if "error" not in g:
        L.append(f"  FINRA margin debt {g['month']}: ${g['debit_musd'] / 1e6:.3f}T, m/m {g['mom_pct']:+}%, y/y {g['yoy_pct']:+}% ({g['yoy_pctile']}th pct since {g['yoy_pctile_since']}), {g['off_record_pct']}% vs record {g['record_month']}")
    s = r.get("spy", {})
    if "error" not in s:
        L.append(f"  SPY flows to {s['as_of']}: 1d {B(s['flow_1d_usd'])} (z {s['flow_1d_z_1y']}), 5d {B(s['flow_5d_usd'])} (z {s['flow_5d_z_1y']}), 20d {B(s['flow_20d_usd'])}")
    v = r.get("ivv", {})
    if "error" not in v and v.get("shares_out"):
        L.append(f"  IVV shares out {v['shares_out']:,.0f} as of {v.get('as_of')}" + (f", flow since {v['flow_since']} {B(v['flow_usd'])}" if v.get("flow_usd") is not None else ""))
    lv = r.get("lev", {})
    for idx, p1 in (lv.get("per_1pct_usd") or {}).items():
        e = (lv.get("last_session") or {}).get(idx)
        L.append(f"  Lev-ETF rebalance {idx}: {B(p1)} per 1% move" + (f"; last session {e['as_of']} index {e['index_ret_pct']:+}% -> {B(e['flow'])}" if e else ""))
    for f in r.get("flags", []): L.append(f"  FLAG: {f}")
    for gp in r.get("gaps", []): L.append(f"  gap: {gp}")
    return "\n".join(L)


def _load_prev(path):
    if not path or not Path(path).exists(): return None
    d = json.loads(Path(path).read_text())
    return d.get("data", d)  # accepts the ArtifactData out_dir file or the bare data object


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "output" / "flows_latest.json"))
    ap.add_argument("--desk", help="write Desk Daily docs to this path")
    ap.add_argument("--prev", help="current meta/flows doc as JSON")
    ap.add_argument("--date", default=date.today().isoformat())
    a = ap.parse_args()
    res = run(_load_prev(a.prev))
    if a.desk:
        Path(a.desk).write_text(json.dumps(desk_docs(res, a.date), indent=1))
    else:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, indent=1))
    print(summary(res))


if __name__ == "__main__":
    main()
