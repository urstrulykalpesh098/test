"""Eye View flows tracker: positioning and flows from primary sources only.

Sources (all free, all primary):
  CFTC  Traders in Financial Futures, futures only (Socrata API publicreporting.cftc.gov, dataset gpe5-46if)
  FINRA margin statistics (monthly debit balances, Excel back to 1997)
  SSGA  SPY daily NAV / shares outstanding history (navhist xlsx)
  iShares IVV product page (shares outstanding snapshot)
  ProShares fund pages (net assets of leveraged and inverse index ETFs)

Analysis only. Not investment advice. Every number carries its source and as-of date;
anything we could not fetch is reported as missing, never filled in.

Usage:  python analyses/flows/flows.py [--out analyses/output/flows_latest.json] [--move-spx 1.0 --move-ndx 1.0 --move-rut 1.0]
"""
import argparse, io, json, math, re, statistics as st, sys, urllib.request, urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
HERE = Path(__file__).resolve().parent
SNAP = HERE / "data" / "etf_snapshots.csv"   # our own daily log of issuer snapshots (builds flow history over time)


def get(url, binary=False, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
    return b if binary else b.decode("utf-8", "replace")


def pctile(x, xs):
    xs = [v for v in xs if v is not None]
    return round(100 * sum(v <= x for v in xs) / len(xs)) if xs else None


def zscore(x, xs):
    xs = [v for v in xs if v is not None]
    if len(xs) < 10: return None
    sd = st.pstdev(xs)
    return round((x - st.mean(xs)) / sd, 2) if sd else None


# ---------------------------------------------------------------- CFTC positioning
COT_MARKETS = {  # consolidated codes fold the E-mini and micro contracts together
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
            out[name] = {"error": str(e)}; continue
        if not rows:
            out[name] = {"error": "no rows"}; continue
        f = lambda r, k: int(float(r.get(k, 0) or 0))
        def nets(r):
            oi = f(r, "open_interest_all") or 1
            am = f(r, "asset_mgr_positions_long") - f(r, "asset_mgr_positions_short")
            lf = f(r, "lev_money_positions_long") - f(r, "lev_money_positions_short")
            dl = f(r, "dealer_positions_long_all") - f(r, "dealer_positions_short_all")
            return {"asset_mgr_net": am, "lev_funds_net": lf, "dealer_net": dl, "oi": oi,
                    "asset_mgr_net_pct_oi": round(100 * am / oi, 1), "lev_funds_net_pct_oi": round(100 * lf / oi, 1)}
        hist = [nets(r) for r in rows]
        now, prev = hist[0], (hist[1] if len(hist) > 1 else None)
        rec = {"report_date": rows[0]["report_date_as_yyyy_mm_dd"][:10], "contract": rows[0]["market_and_exchange_names"],
               "units": rows[0].get("contract_units"), **now, "weeks_of_history": len(hist)}
        for k in ("asset_mgr_net", "lev_funds_net", "dealer_net"):
            rec[k + "_wow"] = now[k] - prev[k] if prev else None
        for k in ("asset_mgr_net_pct_oi", "lev_funds_net_pct_oi"):
            series = [h[k] for h in hist]
            rec[k + "_pctile_3y"] = pctile(now[k], series)
            rec[k + "_z_3y"] = zscore(now[k], series)
        out[name] = rec
    return {"source": "CFTC Traders in Financial Futures, futures only (publicreporting.cftc.gov dataset gpe5-46if)",
            "note": "Positions as of Tuesday; CFTC publishes Friday 3:30 pm ET (holiday weeks slip). Net = long - short contracts.",
            "markets": out}


# ---------------------------------------------------------------- FINRA margin debt
FINRA_XLSX = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"
FINRA_PAGE = "https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics"


def margin():
    rows = []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(get(FINRA_XLSX, binary=True)), read_only=True)
        for r in wb.worksheets[0].iter_rows(values_only=True):
            if r and isinstance(r[0], str) and re.match(r"\d{4}-\d{2}$", r[0]) and isinstance(r[1], (int, float)):
                rows.append((r[0], float(r[1]), r[2], r[3]))
        src = FINRA_XLSX
    except Exception as e:  # fall back to the 13 months shown on the HTML page
        t = re.sub(r"<[^>]+>", " ", get(FINRA_PAGE))
        mon = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
        for m in re.finditer(r"([A-Z][a-z]{2})-(\d{2})\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)", t):
            rows.append((f"20{m.group(2)}-{mon[m.group(1)]:02d}", float(m.group(3).replace(",", "")),
                         float(m.group(4).replace(",", "")), float(m.group(5).replace(",", ""))))
        src = FINRA_PAGE + f" (xlsx failed: {e})"
    rows.sort()
    if not rows: return {"error": "no FINRA rows"}
    d = {m: v for m, v, *_ in rows}
    last_m, last = rows[-1][0], rows[-1][1]
    y, mo = map(int, last_m.split("-"))
    m1, m12 = d.get(_shift(y, mo, -1)), d.get(_shift(y, mo, -12))
    peak_m = max(d, key=d.get)
    yoy = [(d[m] / d[_shift(*map(int, m.split('-')), -12)] - 1) * 100 for m in d if _shift(*map(int, m.split('-')), -12) in d]
    cur_yoy = (last / m12 - 1) * 100 if m12 else None
    return {"source": src, "note": "Debit balances in customers' securities margin accounts, $ millions, month-end. Published about the third week of the next month.",
            "month": last_m, "debit_balances_musd": last,
            "mom_pct": round((last / m1 - 1) * 100, 2) if m1 else None,
            "yoy_pct": round(cur_yoy, 1) if cur_yoy is not None else None,
            "yoy_pctile_since_1998": pctile(cur_yoy, yoy) if cur_yoy is not None else None,
            "record_month": peak_m, "record_musd": d[peak_m], "off_record_pct": round((last / d[peak_m] - 1) * 100, 1),
            "free_credit_cash_musd": rows[-1][2], "free_credit_margin_musd": rows[-1][3],
            "last_13": [{"month": m, "debit": v} for m, v, *_ in rows[-13:]]}


def _shift(y, m, k):
    t = y * 12 + (m - 1) + k
    return f"{t // 12}-{t % 12 + 1:02d}"


# ---------------------------------------------------------------- ETF flows
SPY_XLSX = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/navhist-us-en-spy.xlsx"
IVV_PAGE = "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf"


def spy_flows():
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(get(SPY_XLSX, binary=True)), read_only=True)
    rows = []
    for r in wb.worksheets[0].iter_rows(values_only=True):
        if r and isinstance(r[0], str) and re.match(r"\d{2}-[A-Za-z]{3}-\d{4}", r[0]) and isinstance(r[2], (int, float)):
            rows.append((datetime.strptime(r[0], "%d-%b-%Y").date(), float(r[1]), float(r[2]), float(r[3])))
    rows.sort()
    fl = [(rows[i][0], (rows[i][2] - rows[i - 1][2]) * rows[i][1]) for i in range(1, len(rows))]  # $ flow = dShares x NAV
    last250 = [f for _, f in fl[-250:]]
    s5 = [sum(last250[i - 5:i]) for i in range(5, len(last250) + 1)]
    d0, f0 = fl[-1]
    return {"source": SPY_XLSX, "note": "Flow = change in shares outstanding x NAV. SSGA's share count can lag creations/redemptions by a day; read single days loosely, 5-day sums more firmly.",
            "as_of": d0.isoformat(), "aum_usd": rows[-1][3], "nav": rows[-1][1], "shares_out": rows[-1][2],
            "flow_1d_usd": round(f0), "flow_5d_usd": round(sum(f for _, f in fl[-5:])), "flow_20d_usd": round(sum(f for _, f in fl[-20:])),
            "flow_1d_z_1y": zscore(f0, last250), "flow_5d_z_1y": zscore(s5[-1], s5) if s5 else None,
            "last_10": [{"date": d.isoformat(), "flow_usd": round(f)} for d, f in fl[-10:]]}


def ishares_snapshot(url=IVV_PAGE, ticker="IVV"):
    t = get(url).replace("&quot;", '"')
    blk = re.search(r'"sharesOutstanding":\{([^}]*)\}', t)
    blk = blk.group(1) if blk else ""
    so = re.search(r'"formattedValue":"([\d,]+)"', blk)
    asof = re.search(r'"formattedAsOfDate":"([^"]+)"', blk)
    nav = re.search(r'"name":"NAV as of","value":"([\d.,]+)"', t)
    na = re.search(r'"name":"Net Assets of Fund","value":"\$([\d.,]+)"', t)
    return {"ticker": ticker, "source": url, "shares_out": float(so.group(1).replace(",", "")) if so else None,
            "shares_as_of": _isodate(asof.group(1)) if asof else None, "net_assets_usd": float(na.group(1).replace(",", "")) if na else None,
            "nav_rounded": float(nav.group(1).replace(",", "")) if nav else None}


def _isodate(s):
    for f in ("%Y-%m-%d", "%b %d, %Y"):
        try: return datetime.strptime(s.strip(), f).date().isoformat()
        except ValueError: pass
    return s


def log_snapshot(s, today):
    """Append today's issuer snapshot so day-over-day flows exist for funds without a history file."""
    SNAP.parent.mkdir(parents=True, exist_ok=True)
    lines = SNAP.read_text().splitlines() if SNAP.exists() else ["fetched,ticker,shares_as_of,shares_out,net_assets_usd"]
    key = f",{s['ticker']},{s['shares_as_of']},"
    if s["shares_out"] and not any(key in l for l in lines):
        lines.append(f"{today},{s['ticker']},{s['shares_as_of']},{s['shares_out']:.0f},{s['net_assets_usd'] or ''}")
        SNAP.write_text("\n".join(lines) + "\n")
    prev = [l.split(",") for l in lines[1:] if l.split(",")[1] == s["ticker"] and l.split(",")[2] != s["shares_as_of"]]
    if prev and s["shares_out"] and s["net_assets_usd"]:
        p = prev[-1]; px = s["net_assets_usd"] / s["shares_out"]
        s["flow_since_prev_usd"] = round((s["shares_out"] - float(p[3])) * px); s["prev_shares_as_of"] = p[2]
    return s


# ---------------------------------------------------------------- leveraged ETF rebalance
# (ticker, index, leverage). Direxion (SPXL/SPXS/TNA/TZA/SOXL) blocks automated requests, so it is listed as missing.
LEV_FUNDS = [("TQQQ", "Nasdaq-100", 3), ("SQQQ", "Nasdaq-100", -3), ("QLD", "Nasdaq-100", 2), ("QID", "Nasdaq-100", -2),
             ("UPRO", "S&P 500", 3), ("SPXU", "S&P 500", -3), ("SSO", "S&P 500", 2), ("SDS", "S&P 500", -2),
             ("URTY", "Russell 2000", 3), ("SRTY", "Russell 2000", -3)]
MISSING_LEV = ["SPXL", "SPXS", "TNA", "TZA", "SOXL", "SOXS (Direxion: site refuses automated requests)"]


def proshares_aum(tk):
    url = f"https://www.proshares.com/our-etfs/leveraged-and-inverse/{tk.lower()}"
    t = get(url)
    m = re.search(r'id="snapshot-netAssets"[^>]*>\$([\d,]+)', t)
    return (float(m.group(1).replace(",", "")) if m else None), url


def lev_rebalance(moves):
    """Hedge a daily-reset fund must trade near the close: L(L-1) x r x AUM, in dollars of the index.
    Always in the direction of the day's move (buy on up days, sell on down days), for bull and bear funds alike."""
    funds, per_idx = [], {}
    for tk, idx, L in LEV_FUNDS:
        try:
            aum, url = proshares_aum(tk)
        except Exception as e:
            funds.append({"ticker": tk, "error": str(e)}); continue
        if aum is None:
            funds.append({"ticker": tk, "error": "net assets not found on page"}); continue
        k = L * (L - 1)
        per1 = k * 0.01 * aum
        funds.append({"ticker": tk, "index": idx, "leverage": L, "aum_usd": aum, "per_1pct_move_usd": round(per1), "source": url})
        per_idx[idx] = per_idx.get(idx, 0) + per1
    est = {}
    for idx, p1 in per_idx.items():
        mv = moves.get(idx)
        est[idx] = {"per_1pct_move_usd": round(p1), "assumed_move_pct": mv,
                    "est_close_flow_usd": round(p1 * mv) if mv is not None else None}
    return {"source": "ProShares fund pages (net assets as shown on fetch day; page does not state the as-of date, usually the prior close)",
            "formula": "flow = L(L-1) x r x AUM, summed over funds tracking the same index",
            "caveats": ["Covers ProShares index funds only; Direxion funds missing: " + ", ".join(MISSING_LEV),
                        "AUM should be start-of-day; same-day creations/redemptions and swap resets make the real number differ",
                        "Single-stock leveraged ETFs (e.g. NVDA, TSLA 2x) not included"],
            "funds": funds, "by_index": est}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "output" / "flows_latest.json"))
    ap.add_argument("--move-spx", type=float, default=None, help="S&P 500 move in %% for the rebalance estimate")
    ap.add_argument("--move-ndx", type=float, default=None)
    ap.add_argument("--move-rut", type=float, default=None)
    a = ap.parse_args()
    today = date.today().isoformat()
    res = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "disclaimer": "Analysis only. Not investment advice."}
    for key, fn in [("positioning", cot), ("margin_debt", margin), ("etf_flows_spy", spy_flows)]:
        try: res[key] = fn()
        except Exception as e: res[key] = {"error": f"{type(e).__name__}: {e}"}
    try: res["etf_flows_ivv"] = log_snapshot(ishares_snapshot(), today)
    except Exception as e: res["etf_flows_ivv"] = {"error": f"{type(e).__name__}: {e}"}
    res["lev_etf_rebalance"] = lev_rebalance({"S&P 500": a.move_spx, "Nasdaq-100": a.move_ndx, "Russell 2000": a.move_rut})
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1))
    print(summary(res))


def B(x): return "n/a" if x is None else f"{x / 1e9:+.2f}B"


def summary(r):
    L = ["FLOWS READOUT (analysis only, not investment advice)"]
    p = r.get("positioning", {}).get("markets", {})
    for n in ("S&P 500", "Nasdaq-100", "Russell 2000", "VIX", "10Y Treasury"):
        m = p.get(n, {})
        if "error" in m or not m: L.append(f"  {n}: missing ({m.get('error')})"); continue
        L.append(f"  CFTC {n} ({m['report_date']}): asset mgrs net {m['asset_mgr_net']:+,} ({m['asset_mgr_net_pct_oi']}% OI, {m['asset_mgr_net_pct_oi_pctile_3y']}th pctile 3y, wow {m['asset_mgr_net_wow']:+,}); "
                 f"lev funds net {m['lev_funds_net']:+,} ({m['lev_funds_net_pct_oi']}% OI, {m['lev_funds_net_pct_oi_pctile_3y']}th pctile, wow {m['lev_funds_net_wow']:+,})")
    g = r.get("margin_debt", {})
    if "error" not in g:
        L.append(f"  FINRA margin debt {g['month']}: ${g['debit_balances_musd'] / 1e6:.3f}T, m/m {g['mom_pct']:+}%, y/y {g['yoy_pct']:+}% ({g['yoy_pctile_since_1998']}th pctile since 1998), {g['off_record_pct']}% vs record {g['record_month']}")
    s = r.get("etf_flows_spy", {})
    if "error" not in s:
        L.append(f"  SPY flows to {s['as_of']}: 1d {B(s['flow_1d_usd'])} (z {s['flow_1d_z_1y']}), 5d {B(s['flow_5d_usd'])} (z {s['flow_5d_z_1y']}), 20d {B(s['flow_20d_usd'])}")
    else: L.append(f"  SPY flows missing: {s['error']}")
    v = r.get("etf_flows_ivv", {})
    L.append(f"  IVV shares out {v.get('shares_out')} as of {v.get('shares_as_of')}" + (f", flow since {v['prev_shares_as_of']} {B(v['flow_since_prev_usd'])}" if "flow_since_prev_usd" in v else " (flow needs a second daily snapshot)"))
    for idx, e in r.get("lev_etf_rebalance", {}).get("by_index", {}).items():
        L.append(f"  Lev-ETF close rebalance, {idx}: {B(e['per_1pct_move_usd'])} per 1% move" + (f"; at {e['assumed_move_pct']:+}% = {B(e['est_close_flow_usd'])}" if e["est_close_flow_usd"] is not None else ""))
    return "\n".join(L)


if __name__ == "__main__":
    main()
