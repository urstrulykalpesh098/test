"""God's Eye View: a map of how money and stress move between the markets the desk already tracks.

Context only. Analysis only. Not investment advice. Stdlib only.

What it does
  1. Reads the backbone history files (analyses/data/history/*.csv) and the trackers' latest
     outputs (flows, credit, auctions, canada, vixterm).
  2. Gives every node on the map a "pressure" score: + means tightening or stress building,
     - means easing. Score = z-score of the node's recent change (and level, for spread-type
     nodes) against its own trailing three years.
  3. Tests every link it can on history: correlation of non-overlapping 4-week changes since
     2010, the same split into three eras (does it hold up?), a lead test (does A's last
     4 weeks say anything about B's next 4?), and a gap test (when A was under pressure and
     B had not followed, how often did B follow within 4 weeks, versus B's normal rate).
     Links with no free history are labelled inferred (theory only) or mechanical (a formula).
  4. Builds weekly snapshots for the last three years, marks each link as passing pressure,
     gap (upstream moved, downstream has not), or quiet, and writes a short plain narrative.

Nothing here creates information. It puts the desk's numbers next to each other with the
evidence for each connection, so you can see which stories the data supports today.

    python analyses/godseye/godseye.py            -> analyses/output/godseye/godseye.json + readout
"""
import argparse, csv, json, math
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HIST = ROOT / "analyses" / "data" / "history"
OUT = ROOT / "analyses" / "output"
VERSION = "godseye v1.0 (2026-11-26)"
TEST_START = "2010-01-01"
WEEKS = 156          # snapshots and z-score window: three years of weeks
STEP = 4             # change horizon in weeks

# ---------------------------------------------------------------- nodes
# col: 0 source of money, 1 plumbing and rates, 2 risk appetite, 3 equities and positioning, 4 outer ring
# mode: pct = % change, diff = change in units, ratio = series a / series b then diff
# orient: +1 means a rise is pressure/tightening, -1 means a fall is pressure
# use: chg = recent change only, mix = change and level
NODES = [
    dict(id="fed_bs", label="Fed balance sheet", col=0, row=0, sid="WALCL", mode="pct", orient=-1, use="chg",
         unit="%", what="Total Fed assets. Shrinking (QT) drains cash from the system.", src="FRED WALCL (weekly)"),
    dict(id="fed_rate", label="Fed policy rate", col=0, row=1, sid="DFF", mode="diff", orient=1, use="mix",
         unit="bp", what="Effective fed funds rate. Higher means money costs more.", src="FRED DFF"),
    dict(id="rrp", label="Reverse repo cushion", col=0, row=2, sid="RRPONTSYD", mode="diff", orient=-1, use="mix",
         unit="$bn", what="Cash parked at the Fed overnight. A thin cushion means less spare cash to absorb shocks.", src="FRED RRPONTSYD"),
    dict(id="auctions", label="Treasury auctions", col=0, row=3, tracker=True,
         what="How well new Treasury supply is absorbed: bid-to-cover and the share dealers are left holding.",
         src="TreasuryDirect auction results via analyses/trackers/auctions.py"),
    dict(id="oil", label="Oil", col=0, row=4, sid="DCOILWTICO", mode="pct", orient=1, use="chg",
         unit="%", what="WTI crude. Rising oil feeds inflation worries and, for Canada, the currency.", src="FRED DCOILWTICO"),

    dict(id="repo", label="Repo funding", col=1, row=0, sid="SOFR", sid2="DFF", mode="spread", orient=1, use="mix",
         unit="bp", what="SOFR minus fed funds. When overnight secured money costs more than policy, cash is scarce.", src="FRED SOFR, DFF; NY Fed via credit tracker"),
    dict(id="infl", label="Inflation expectations", col=1, row=1, sid="T10YIE", mode="diff", orient=1, use="chg",
         unit="bp", what="10-year breakeven inflation.", src="FRED T10YIE"),
    dict(id="yields", label="10y Treasury yield", col=1, row=2, sid="DGS10", mode="diff", orient=1, use="chg",
         unit="bp", what="The price of long-term money for everyone.", src="FRED DGS10"),
    dict(id="real", label="Real yields", col=1, row=3, sid="DFII10", mode="diff", orient=1, use="chg",
         unit="bp", what="10-year TIPS yield: what money earns after inflation. Weighs on long-duration growth stocks.", src="FRED DFII10"),
    dict(id="dollar", label="US dollar", col=1, row=4, sid="DTWEXBGS", mode="pct", orient=1, use="chg",
         unit="%", what="Broad trade-weighted dollar. A rising dollar tightens money for the rest of the world.", src="FRED DTWEXBGS"),

    dict(id="fincond", label="Financial conditions", col=2, row=0, sid="NFCI", mode="diff", orient=1, use="mix",
         unit="pts", what="Chicago Fed NFCI: 100+ measures of how easy it is to borrow and raise money.", src="FRED NFCI (weekly)"),
    dict(id="credit", label="Corporate credit", col=2, row=1, sid="BAMLH0A0HYM2", mode="diff", orient=1, use="mix",
         unit="bp", what="High-yield bond spread over Treasuries. Widening means lenders want more to take risk.", src="FRED ICE BofA HY OAS (3 years kept)"),
    dict(id="vol", label="VIX curve", col=2, row=2, sid="CBOE_VIX", sid2="CBOE_VIX3M", mode="ratio", orient=1, use="mix",
         unit="", what="VIX divided by 3-month VIX. Above 1 (backwardation) means near-term fear exceeds longer-term.", src="Cboe VIX and VIX3M history"),
    dict(id="positioning", label="Futures positioning", col=2, row=3, tracker=True,
         what="CFTC: how hedge funds and asset managers are positioned in S&P and VIX futures. Crowding is fragility, not direction.",
         src="CFTC Traders in Financial Futures via analyses/flows/flows.py"),
    dict(id="margin", label="Margin debt", col=2, row=4, tracker=True,
         what="FINRA customer margin balances. High leverage amplifies falls through margin calls.", src="FINRA margin statistics via flows.py"),

    dict(id="spx", label="S&P 500", col=3, row=0, sid="CBOE_SPX", mode="pct", orient=-1, use="chg",
         unit="%", what="US large caps. Falling counts as pressure.", src="Cboe SPX history"),
    dict(id="ndx", label="Nasdaq", col=3, row=1, sid="NASDAQCOM", mode="pct", orient=-1, use="chg",
         unit="%", what="Growth and tech heavy. Most sensitive to real yields.", src="FRED NASDAQCOM"),
    dict(id="etf", label="ETF flows", col=3, row=2, tracker=True,
         what="SPY creations and redemptions, and the forced end-of-day rebalancing of leveraged ETFs.", src="SSGA SPY, ProShares via flows.py"),
    dict(id="cad", label="Canada (USD/CAD)", col=3, row=3, sid="DEXCAUS", mode="pct", orient=1, use="chg",
         unit="%", what="CAD per USD. Rising means a weaker loonie, which usually comes with risk-off or falling oil.", src="FRED DEXCAUS; Bank of Canada via canada tracker"),
]

# ---------------------------------------------------------------- links
# sign: expected sign of the raw co-movement (a up -> b up = +1). kind: tested / inferred / mechanical
EDGES = [
    ("fed_bs", "rrp", 1, "tested", "QT drained cash, and the reverse repo pool was the first place it came from."),
    ("fed_bs", "repo", -1, "tested", "Fewer reserves in the system makes overnight cash dearer."),
    ("rrp", "repo", -1, "tested", "Once the reverse repo cushion is gone, repo rates feel every cash drain."),
    ("auctions", "repo", 0, "inferred", "Auction settlement pulls cash out of money funds and dealers on settlement days."),
    ("auctions", "yields", 0, "inferred", "Weak demand at auctions (dealers left holding more) pushes long yields up. Tails need intraday data we don't have."),
    ("fed_rate", "yields", 1, "tested", "Policy rate expectations anchor the front of the curve and pull on the 10-year."),
    ("oil", "infl", 1, "tested", "Energy prices move inflation expectations."),
    ("infl", "yields", 1, "tested", "Higher expected inflation means investors ask more to lend long."),
    ("yields", "real", 1, "tested", "Nominal yield = real yield + inflation expectations."),
    ("real", "ndx", -1, "tested", "Higher real yields discount far-off growth profits more heavily."),
    ("yields", "spx", -1, "tested", "Higher rates compete with stocks. This one flips sign by era, see the eras."),
    ("yields", "dollar", 1, "tested", "Higher US yields draw money into dollars."),
    ("repo", "fincond", 1, "tested", "Funding strain shows up in the broad conditions index."),
    ("fincond", "credit", 1, "tested", "When borrowing gets harder, junk spreads widen."),
    ("credit", "spx", -1, "tested", "Credit and equity price the same company risk; credit often moves first."),
    ("credit", "vol", 1, "tested", "Wider spreads and near-term fear go together."),
    ("vol", "spx", -1, "tested", "An inverted VIX curve comes with falling stocks."),
    ("vol", "positioning", 0, "inferred", "Volatility-targeting funds and CTAs cut exposure as volatility rises."),
    ("positioning", "spx", 0, "inferred", "Crowded positioning makes moves bigger when it unwinds."),
    ("margin", "spx", 0, "inferred", "High margin balances turn falls into forced selling."),
    ("ndx", "etf", 0, "mechanical", "Leveraged ETFs must buy after up days and sell after down days: flow = L(L-1) x return x assets."),
    ("etf", "ndx", 0, "inferred", "That rebalancing lands in the last minutes of trading and can extend the day's move."),
    ("dollar", "cad", 1, "tested", "A broadly stronger US dollar lifts USD/CAD."),
    ("oil", "cad", -1, "tested", "Canada exports oil: higher oil usually means a stronger loonie."),
    ("spx", "cad", -1, "tested", "Risk-off days weaken the loonie."),
]

OFF_MAP = [
    ("Sectors", "No free daily sector index history reachable from the desk (sector ETF prices sit behind blocked or paid sources)."),
    ("Policy pipeline (Texas bills, Federal Register)", "Counts of bills and rules have no tested path to any market here; most filed bills never pass."),
    ("TSX", "TMX, Yahoo and Stooq are blocked from the desk's cloud box."),
    ("Auction tails", "Need intraday when-issued yields, not free. Bid-to-cover and dealer share are used instead."),
    ("CDS", "No free primary source. HY OAS stands in for credit risk."),
]


# ---------------------------------------------------------------- data
def load(sid):
    out = {}
    p = HIST / f"{sid}.csv"
    if not p.exists():
        return out
    with open(p, newline="") as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            if len(row) < 2 or row[1] in ("", "."):
                continue
            try:
                out[row[0]] = float(row[1])
            except ValueError:
                pass
    return out


def jload(name):
    p = OUT / name
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def weekly(series, grid, max_stale=10):
    """Last value on or before each grid date, None if older than max_stale days."""
    ds = sorted(series)
    out, j, last_d = [], 0, None
    for g in grid:
        while j < len(ds) and ds[j] <= g:
            last_d = ds[j]
            j += 1
        if last_d is None or (date.fromisoformat(g) - date.fromisoformat(last_d)).days > max_stale:
            out.append(None)
        else:
            out.append(series[last_d])
    return out


def node_level(n, grid):
    a = weekly(load(n["sid"]), grid)
    if n["mode"] in ("spread", "ratio"):
        b = weekly(load(n["sid2"]), grid)
        res = []
        for x, y in zip(a, b):
            if x is None or y is None or (n["mode"] == "ratio" and not y):
                res.append(None)
            else:
                res.append((x - y) * 100 if n["mode"] == "spread" else x / y)
        return res
    if n["id"] == "rrp":
        return [None if x is None else x for x in a]
    return a


def change(n, lv, i, k=STEP):
    if i - k < 0 or lv[i] is None or lv[i - k] is None:
        return None
    if n["mode"] == "pct":
        return (lv[i] / lv[i - k] - 1) * 100 if lv[i - k] else None
    if n["mode"] == "diff" and n.get("unit") == "bp":
        return (lv[i] - lv[i - k]) * 100
    return lv[i] - lv[i - k]


def zscore(x, hist, min_n=26):
    h = [v for v in hist if v is not None]
    if x is None or len(h) < min_n:
        return None
    m = sum(h) / len(h)
    sd = math.sqrt(sum((v - m) ** 2 for v in h) / (len(h) - 1))
    return 0.0 if sd == 0 else (x - m) / sd


def pctile(x, hist):
    h = [v for v in hist if v is not None]
    if x is None or not h:
        return None
    return round(100 * sum(1 for v in h if v <= x) / len(h))


def clip(x, lo=-3.0, hi=3.0):
    return max(lo, min(hi, x))


def corr(xs, ys):
    pr = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pr)
    if n < 12:
        return None, n
    mx = sum(p[0] for p in pr) / n
    my = sum(p[1] for p in pr) / n
    sx = math.sqrt(sum((p[0] - mx) ** 2 for p in pr))
    sy = math.sqrt(sum((p[1] - my) ** 2 for p in pr))
    if sx == 0 or sy == 0:
        return None, n
    return sum((p[0] - mx) * (p[1] - my) for p in pr) / (sx * sy), n


def fisher_ci(r, n):
    if r is None or n < 5:
        return None
    z = math.atanh(max(-0.999, min(0.999, r)))
    se = 1 / math.sqrt(n - 3)
    return [round(math.tanh(z - 1.96 * se), 2), round(math.tanh(z + 1.96 * se), 2)]


def strength_label(r_signed):
    if r_signed is None:
        return "untested"
    if r_signed < 0.05:
        return "contradicts" if r_signed < -0.1 else "none"
    if r_signed < 0.2:
        return "weak"
    if r_signed < 0.4:
        return "moderate"
    return "strong"


# ---------------------------------------------------------------- tracker nodes (today only)
def tracker_states(flows, credit, auctions, canada):
    st = {}
    if auctions and auctions.get("recent"):
        rec = auctions["recent"][-6:]
        dz = [r.get("dealer_pct_z") for r in rec if r.get("dealer_pct_z") is not None]
        bz = [r.get("btc_z") for r in rec if r.get("btc_z") is not None]
        p = ((sum(dz) / len(dz) if dz else 0) - (sum(bz) / len(bz) if bz else 0)) / 1.4
        verd = {}
        for r in rec:
            verd[r.get("verdict", "?")] = verd.get(r.get("verdict", "?"), 0) + 1
        last = rec[-1]
        st["auctions"] = dict(p=round(clip(p), 2), as_of=last.get("date"),
                              text=f"Last {len(rec)} auctions: " + ", ".join(f"{v} {k}" for k, v in sorted(verd.items(), key=lambda x: -x[1]))
                              + f". Latest {last.get('term')} {last.get('kind', '').lower()}: bid-to-cover {last.get('btc')} vs {last.get('btc_avg')} avg, dealers {last.get('dealer_pct')}% vs {last.get('dealer_pct_avg')}%.")
    if flows:
        pos = (flows.get("positioning") or {}).get("markets") or {}
        sp, vx = pos.get("S&P 500") or {}, pos.get("VIX") or {}
        parts, txt = [], []
        if sp.get("lev_funds_pctile_3y") is not None:
            parts.append((sp["lev_funds_pctile_3y"] - 50) / 25)
            txt.append(f"hedge funds' S&P futures net at the {sp['lev_funds_pctile_3y']}th percentile of 3 years")
        if vx.get("lev_funds_pctile_3y") is not None:
            parts.append((50 - vx["lev_funds_pctile_3y"]) / 25)
            txt.append(f"their VIX futures net at the {vx['lev_funds_pctile_3y']}th (short volatility)")
        if parts:
            st["positioning"] = dict(p=round(clip(sum(parts) / len(parts)), 2), as_of=sp.get("report_date"),
                                     text="Crowding: " + "; ".join(txt) + ". High = crowded, which is fragility, not a direction call.")
        m = flows.get("margin_debt") or {}
        if m.get("yoy_pctile") is not None:
            st["margin"] = dict(p=round(clip((m["yoy_pctile"] - 50) / 25), 2), as_of=m.get("month"),
                                text=f"${m['debit_musd'] / 1e6:.2f}T in {m['month']}, {m['yoy_pct']:+.1f}% on the year ({m['yoy_pctile']}th percentile of yearly growth since 1998), {m['off_record_pct']:+.1f}% off the {m['record_month']} record.")
        spy, lev = flows.get("spy") or {}, flows.get("lev") or {}
        if spy:
            lev_tot = sum((v or {}).get("flow", 0) for v in (lev.get("last_session") or {}).values())
            p = -(spy.get("flow_5d_z_1y") or 0) + clip(-lev_tot / 2e9, -1, 1)
            st["etf"] = dict(p=round(clip(p), 2), as_of=spy.get("as_of"),
                             text=f"SPY: ${spy.get('flow_5d_usd', 0) / 1e9:+.1f}bn over 5 days, ${spy.get('flow_20d_usd', 0) / 1e9:+.1f}bn over 20. "
                                  f"Leveraged ETF rebalance last session: ${lev_tot / 1e9:+.2f}bn (negative = forced selling into the close).")
    return st


def today_extras(credit, canada, vixterm):
    ex = {}
    if credit:
        f = credit.get("funding") or {}
        s = credit.get("spreads") or {}
        bits = []
        if (f.get("sofr") or {}).get("minus_iorb_bp") is not None:
            bits.append(f"SOFR {f['sofr']['minus_iorb_bp']:+d}bp vs IORB, above it on {f['sofr'].get('days_above_iorb_20')} of 20 days")
        if "CP minus T-bill" in s and s["CP minus T-bill"].get("last") is not None:
            bits.append(f"CP minus T-bill {s['CP minus T-bill']['last'] * 100:.0f}bp")
        if (f.get("rrp") or {}).get("last_usd") is not None:
            bits.append(f"reverse repo ${f['rrp']['last_usd'] / 1e9:.1f}bn")
        if bits:
            ex["repo"] = "Today (NY Fed): " + "; ".join(bits) + "."
        cc = s.get("BAMLH0A3HYC")
        if cc:
            ex["credit"] = f"CCC spread {cc['last']}% ({cc['pctile_3y']}th pct of 3y, {cc['chg_20']:+.0f}bp in 20 days)."
    if canada:
        lv = canada.get("levels") or {}
        bits = []
        if lv.get("policy"):
            bits.append(f"BoC rate {lv['policy']['last']}%")
        if lv.get("ca10y") and lv.get("us10y"):
            bits.append(f"Canada 10y {lv['ca10y']['last']}% vs US {lv['us10y']['last']}%")
        if lv.get("usdcad"):
            bits.append(f"USD/CAD {lv['usdcad']['last']} ({lv['usdcad']['pctile_3y']}th pct of 3y)")
        if bits:
            ex["cad"] = "Canada lens: " + "; ".join(bits) + "."
    if vixterm:
        ex["vol"] = (f"VIX9D {vixterm.get('vix9d')}, VIX {vixterm.get('vix')}, VIX3M {vixterm.get('vix3m')}: {vixterm.get('state')} for "
                     f"{vixterm.get('sessions_in_state')} sessions. Desk backtest: adding the curve lifted next-week realized vol forecasts (R2 0.44 to 0.52).")
    return ex


# ---------------------------------------------------------------- build
def ordinal(k):
    return f"{k}{'th' if 10 <= k % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(k % 10, 'th')}"


def fmt_val(n, lv, ch, pc):
    if lv is None:
        return "no data"
    u = n.get("unit", "")
    if n["mode"] == "ratio":
        s = f"{lv:.3f}"
    elif n["id"] == "rrp":
        s = f"${lv:,.1f}bn" if lv < 10 else f"${lv:,.0f}bn"
    elif n["id"] == "fed_bs":
        s = f"${lv / 1e6:.2f}T"
    elif n["mode"] == "spread":
        s = f"{lv:+.0f}bp"
    elif n["mode"] == "pct":
        s = f"{lv:,.2f}" if lv < 100 else f"{lv:,.0f}"
    else:
        s = f"{lv:.2f}" + ("%" if u == "bp" else "")
    if ch is not None:
        cu = "%" if n["mode"] == "pct" else ("bp" if u == "bp" or n["mode"] == "spread" else "")
        s += f", {ch:+.1f}{cu} in 4 wks" if cu != "bp" else f", {ch:+.0f}bp in 4 wks"
    if pc is not None:
        s += f", {ordinal(pc)} pct of 3y"
    return s


def build():
    ends = [max(load(s)) for s in ("CBOE_SPX", "DGS10") if load(s)]
    end = date.fromisoformat(max(ends))
    start = date.fromisoformat(TEST_START) - timedelta(days=7 * (WEEKS + STEP + 2))
    grid = []
    d = end
    while d >= start:
        grid.append(d.isoformat())
        d -= timedelta(days=7)
    grid.reverse()
    ti = next(i for i, g in enumerate(grid) if g >= TEST_START)

    nodes = {n["id"]: n for n in NODES}
    lv, ch, pr = {}, {}, {}
    for n in NODES:
        if n.get("tracker"):
            continue
        L = node_level(n, grid)
        C = [change(n, L, i) for i in range(len(grid))]
        P = []
        for i in range(len(grid)):
            lo = max(0, i - WEEKS)
            zc = zscore(C[i], C[lo:i])
            zl = zscore(L[i], L[lo:i]) if n["use"] == "mix" else None
            zs = [z for z in (zc, zl) if z is not None]
            P.append(None if not zs else round(clip(n["orient"] * sum(zs) / len(zs)), 2))
        lv[n["id"]], ch[n["id"]], pr[n["id"]] = L, C, P

    # ---- link tests
    nonover = list(range(ti, len(grid), STEP))
    eras = [("2010-2015", "2010-01-01", "2016-01-01"), ("2016-2020", "2016-01-01", "2021-01-01"), ("2021-now", "2021-01-01", "2100-01-01")]
    edges = []
    for a, b, sign, kind, why in EDGES:
        e = dict(id=f"{a}>{b}", a=a, b=b, kind=kind, why=why, sign=sign)
        if kind == "tested" and a in ch and b in ch:
            xa = [ch[a][i] for i in nonover]
            xb = [ch[b][i] for i in nonover]
            r, n_ = corr(xa, xb)
            first = next((grid[i] for i in nonover if ch[a][i] is not None and ch[b][i] is not None), None)
            e["test"] = dict(r=None if r is None else round(r, 2), n=n_, ci=fisher_ci(r, n_), since=first,
                             what="correlation of non-overlapping 4-week changes")
            rs = None if r is None else r * sign
            e["strength"] = strength_label(rs)
            e["w"] = 0 if rs is None else round(max(0.0, rs), 2)
            era_r = []
            for nm, lo, hi in eras:
                idx = [i for i in nonover if lo <= grid[i] < hi]
                rr, nn = corr([ch[a][i] for i in idx], [ch[b][i] for i in idx])
                if rr is not None:
                    era_r.append(dict(era=nm, r=round(rr, 2), n=nn))
            e["eras"] = era_r
            flips = [x for x in era_r if x["r"] * sign < -0.1]
            if len(era_r) < 2:
                e["stable"] = "too little history to check eras"
            elif flips:
                e["stable"] = "flips sign by era"
            elif all(x["r"] * sign > 0.05 for x in era_r):
                e["stable"] = "holds in every era"
            else:
                e["stable"] = "mixed"
            lead_a = [ch[a][i] for i in nonover if i + STEP < len(grid)]
            lead_b = [change(nodes[b], lv[b], i + STEP) for i in nonover if i + STEP < len(grid)]
            lr, ln = corr(lead_a, lead_b)
            e["lead"] = dict(r=None if lr is None else round(lr, 2), n=ln,
                             what="A's last 4 weeks vs B's next 4 weeks")
            # gap test (weekly, overlapping, so counts are not independent)
            sp = sign * nodes[a]["orient"] * nodes[b]["orient"]
            gaps = follow = base_n = base_f = 0
            for i in range(ti, len(grid) - STEP):
                pa, pb = pr[a][i], pr[b][i]
                pb2 = pr[b][i + STEP]
                if pa is None or pb is None or pb2 is None:
                    continue
                base_n += 1
                moved = (pb2 - pb) * sp * (1 if pa > 0 else -1) >= 0.75
                if abs(pa) >= 1.25 and (sp * pa * pb <= 0 or abs(pb) < 0.4):
                    gaps += 1
                    follow += moved
                # base: how often B moves that much toward pressure (either sign) in 4 weeks
                base_f += abs(pb2 - pb) >= 0.75 and (pb2 - pb) * (1 if pa > 0 else -1) * sp > 0
            e["gap_test"] = dict(gaps=gaps, followed=follow, rate=None if not gaps else round(follow / gaps, 2),
                                 base=None if not base_n else round(base_f / base_n, 2),
                                 what="weeks A was under pressure and B had not followed; share where B moved toward A within 4 weeks, vs B's usual rate")
        else:
            e["strength"] = kind
            e["w"] = 0.15 if kind == "mechanical" else 0.0
        edges.append(e)

    # ---- snapshots
    flows, credit, auctions, canada, vixterm = (jload("flows_latest.json"), jload("credit_latest.json"),
                                                 jload("auctions_latest.json"), jload("canada_latest.json"), jload("vixterm_latest.json"))
    trk = tracker_states(flows, credit, auctions, canada)
    extras = today_extras(credit, canada, vixterm)
    snaps = []
    for i in range(len(grid) - WEEKS, len(grid)):
        is_today = i == len(grid) - 1
        p, v = {}, {}
        for n in NODES:
            nid = n["id"]
            if n.get("tracker"):
                if is_today and nid in trk:
                    p[nid] = trk[nid]["p"]
                    v[nid] = trk[nid]["text"]
                continue
            if pr[nid][i] is None:
                continue
            p[nid] = pr[nid][i]
            lo = max(0, i - WEEKS)
            v[nid] = fmt_val(n, lv[nid][i], ch[nid][i], pctile(lv[nid][i], lv[nid][lo:i + 1]))
        es = {}
        for e in edges:
            pa, pb = p.get(e["a"]), p.get(e["b"])
            if pa is None or pb is None:
                continue
            sp = (e["sign"] or 1) * nodes[e["a"]]["orient"] * nodes[e["b"]].get("orient", 1) if e["kind"] == "tested" else 1
            aligned = sp * pa * pb > 0
            if abs(pa) >= 0.75 and abs(pb) >= 0.75 and aligned:
                es[e["id"]] = "pass"
            elif abs(pa) >= 1.25 and (not aligned or abs(pb) < 0.4) and (e["kind"] != "tested" or e["w"] >= 0.2):
                es[e["id"]] = "gap"
        chains = []
        lines = story(p, es, edges, nodes, is_today, chains)
        snaps.append(dict(date=grid[i], p=p, v=v, e=es, story=lines, chains=chains))
    if snaps:
        for k, t in extras.items():
            if k in snaps[-1]["v"]:
                snaps[-1]["v"][k] += " " + t

    ndesc = []
    for n in NODES:
        ndesc.append({k: n[k] for k in ("id", "label", "col", "row", "what", "src")} |
                     dict(tracker=bool(n.get("tracker")), orient=n.get("orient", 1)))
    return dict(version=VERSION, built_utc=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d %H:%M"),
                as_of=grid[-1], disclaimer="Context only. Analysis only. Not investment advice.",
                method=("Pressure = z-score of a node's 4-week change (and its level, for spreads, rates and ratios) against its own last 3 years; "
                        "+ is tightening or stress, - is easing. A link is 'passing' when both ends are at least 0.75 and moving the way the link says; "
                        "a 'gap' is when the upstream end is at least 1.25 and the downstream end has not followed. Link strength = correlation of "
                        "non-overlapping 4-week changes since 2010 (or since the data starts), signed so positive means it behaves as the theory says."),
                nodes=ndesc, edges=edges, snapshots=snaps,
                off_map=[dict(name=a, why=b) for a, b in OFF_MAP])


def node_name(nodes, i):
    return nodes[i]["label"]


def story(p, es, edges, nodes, is_today, chains=None):
    s = []
    hot = sorted([(v, k) for k, v in p.items() if v >= 0.75], reverse=True)
    cool = sorted([(v, k) for k, v in p.items() if v <= -0.75])
    if hot:
        names = ", ".join(nodes[k]["label"] for _, k in hot[:4])
        s.append(f"Pressure is highest in {names}." if len(hot) > 1 else f"Pressure is highest in {names}.")
    else:
        s.append("No node is under notable pressure; the map is quiet.")
    # chains of passing edges
    by_a = {}
    for e in edges:
        if es.get(e["id"]) == "pass":
            by_a.setdefault(e["a"], []).append(e)
    def best_chain(want):
        best = []

        def walk(path, seen):
            nonlocal best
            ext = False
            for e in by_a.get(path[-1]["b"], []):
                if e["b"] not in seen and (p.get(e["b"], 0) > 0) == want:
                    ext = True
                    walk(path + [e], seen | {e["b"]})
            if not ext:
                score = sum(x["w"] for x in path) + 0.1 * len(path)
                if not best or score > best[0]:
                    best = [score, path]

        for a in by_a:
            for e in by_a[a]:
                if (p.get(e["b"], 0) > 0) == want:
                    walk([e], {a, e["b"]})
        return best[1] if best else None

    for want, dirn in ((True, "stress"), (False, "easing")):
        path = best_chain(want)
        if not path:
            continue
        chain = " to ".join([nodes[path[0]["a"]]["label"]] + [nodes[e["b"]]["label"] for e in path])
        if chains is not None:
            chains.append(dict(dir=dirn, path=[path[0]["a"]] + [e["b"] for e in path]))
        tested = [e for e in path if e["kind"] == "tested"]
        note = ""
        if tested:
            weakest = min(tested, key=lambda e: e["w"])
            note = f" Weakest tested link: {nodes[weakest['a']]['label']} to {nodes[weakest['b']]['label']} ({weakest['strength']})."
        if len(tested) < len(path):
            note += " Dashed steps are theory only."
        s.append(f"{'Stress' if want else 'Easing'} is passing along {chain}.{note}")
    def lift(e):
        g = e.get("gap_test") or {}
        return (g.get("rate") or 0) - (g.get("base") or 0) if g.get("gaps", 0) >= 8 else -1
    gaps = sorted([e for e in edges if es.get(e["id"]) == "gap"], key=lambda e: -lift(e))
    for e in gaps[:2]:
        gt = e.get("gap_test") or {}
        tail = ""
        if gt.get("rate") is not None and gt.get("gaps", 0) >= 8:
            tail = (f" In past gaps like this the downstream side moved toward it within 4 weeks {round(gt['rate'] * 100)}% of the time, "
                    f"against {round(gt['base'] * 100)}% normally ({gt['gaps']} weeks, overlapping).")
        elif e["kind"] != "tested":
            tail = " This link is theory only (no free history), so treat it as a question, not a signal."
        word = "under pressure" if p.get(e["a"], 0) > 0 else "easing"
        s.append(f"Gap: {nodes[e['a']]['label']} is {word} but {nodes[e['b']]['label']} has not followed.{tail}")
    if cool:
        s.append("Easing: " + ", ".join(nodes[k]["label"] for _, k in cool[:3]) + ".")
    return s


def readout(d):
    t = d["snapshots"][-1]
    lines = [f"GOD'S EYE VIEW {d['as_of']} ({d['disclaimer']})"]
    lines += ["  " + x for x in t["story"]]
    lines.append("  links on history:")
    for e in d["edges"]:
        if e["kind"] == "tested" and e.get("test"):
            lines.append(f"    {e['a']:>8} -> {e['b']:<8} r={e['test']['r']} n={e['test']['n']} {e['strength']}, {e['stable']}, lead r={e['lead']['r']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT / "godseye" / "godseye.json"))
    a = ap.parse_args()
    d = build()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(d, separators=(",", ":")))
    print(readout(d))


if __name__ == "__main__":
    main()
