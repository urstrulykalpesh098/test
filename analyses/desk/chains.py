"""Real SPY option chains for the desk, from free market data APIs.

SOURCES
  marketdata (default)  MarketData.app "Free Forever": 100 credits/day, data is the prior
                        session (24h delayed), includes bid/ask, IV, greeks, open interest.
                        Terms: personal use; storing on your own devices allowed; derived
                        data unrestricted; no redistribution. Works from Canada.
  alpaca                Alpaca Basic (US residents only), kept for reference.


WHAT IT DOES
  summary  Reads today's SPY chain and prints DERIVED numbers only: ATM IV, 25-delta
           skew, fitted skew slopes (for the model fallback), implied move per expiry,
           bid/ask width, dealer gamma estimate, gamma flip level, call and put walls.
  price    Prices a defined-risk structure from real quotes: mid (for marks) and a
           fill price (mid plus half the bid/ask width on every leg, in or out).
           Falls back to the Black-Scholes book model, flagged, if a leg has no
           usable quote.
  selftest Checks the maths on a SYNTHETIC chain built inside this file. It never
           touches the network and its numbers are not market data.

DATA SOURCE AND LIMITS (read before trusting a number)
  * Alpaca Basic (free) plan, options "indicative" feed: Alpaca says its trades are
    delayed 15 minutes and its quotes are "modified" derivatives of OPRA, not real
    exchange quotes. Treat bid/ask widths as approximate.
  * Open interest comes from Alpaca's contracts endpoint (prior-day figure). If it
    is missing, the gamma section is skipped, never guessed.
  * The gamma sign uses the common street assumption that dealers are long calls
    and short puts. That is an assumption, not an observed position.
  * Alpaca's terms: personal, non-commercial use; no republishing the content.
    So this script never writes raw chains anywhere: it prints derived numbers
    only, and the desk stores only those.

AUTH
  MarketData.app: Network secret for host api.marketdata.app, header Authorization,
  value "Bearer <token>". Fallback: env var MARKETDATA_TOKEN.
  Alpaca: keys go in the cloud environment as Network secrets (headers APCA-API-KEY-ID and
  APCA-API-SECRET-KEY for data.alpaca.markets and paper-api.alpaca.markets), which
  the proxy adds to each request. As a local fallback the script also sends env vars
  APCA_API_KEY_ID / APCA_API_SECRET_KEY if they are set.

Run:  python analyses/desk/chains.py summary [--days 45] [--band 0.12]
      python analyses/desk/chains.py price --expiry 2026-12-04 --legs '[[1,"P",700],[-1,"P",690]]'
      python analyses/desk/chains.py selftest
Stdlib only, so a fresh scheduled session can run it with no installs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

DATA = "https://data.alpaca.markets"
TRADE = "https://paper-api.alpaca.markets"
MD = "https://api.marketdata.app"
RATE, DIV = 0.039, 0.012            # same as the paper book's model rules
MODEL_PUT_SKEW, MODEL_CALL_SKEW = 0.9, -0.3  # book's old assumptions (vol pts per 1% OTM), fallback only
WIDE = 0.5                          # a quote wider than 50% of its mid is "wide"
OCC = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")

N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
n = lambda x: math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


# ---------------------------------------------------------------- maths
def bs(S, K, T, iv, kind, r=RATE, q=DIV):
    if T <= 0 or iv <= 0:
        return max(0.0, S - K) if kind == "C" else max(0.0, K - S)
    sd = iv * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + iv * iv / 2) * T) / sd
    d2 = d1 - sd
    if kind == "C":
        return S * math.exp(-q * T) * N(d1) - K * math.exp(-r * T) * N(d2)
    return K * math.exp(-r * T) * N(-d2) - S * math.exp(-q * T) * N(-d1)


def greeks(S, K, T, iv, kind, r=RATE, q=DIV):
    sd = iv * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + iv * iv / 2) * T) / sd
    delta = math.exp(-q * T) * (N(d1) if kind == "C" else N(d1) - 1)
    gamma = math.exp(-q * T) * n(d1) / (S * sd)
    return delta, gamma


def implied_vol(price, S, K, T, kind):
    """Bisection on Black-Scholes. None if the price is outside no-arbitrage bounds."""
    if T <= 0 or price <= 0:
        return None
    lo, hi = 0.01, 3.0
    if not (bs(S, K, T, lo, kind) <= price <= bs(S, K, T, hi, kind)):
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if bs(S, K, T, mid, kind) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def interp(xs, ys, x):
    pts = sorted(zip(xs, ys))
    if not pts:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 != x0 else y0


def years(expiry: dt.date, now: dt.datetime):
    close = dt.datetime.combine(expiry, dt.time(21, 0), tzinfo=dt.timezone.utc)  # 16:00 ET, close enough
    return max((close - now).total_seconds(), 0) / (365.0 * 86400)


# ---------------------------------------------------------------- data
LAST_HEADERS = {}
LOCK_WAIT_S = 330   # MarketData.app one-device lock lasts ~5 minutes


def _get(base, path, params, _retry=True):
    url = f"{base}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if base == MD and os.environ.get("MARKETDATA_TOKEN"):
        req.add_header("Authorization", "Bearer " + os.environ["MARKETDATA_TOKEN"])
    kid, sec = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    if kid and sec:
        req.add_header("APCA-API-KEY-ID", kid)
        req.add_header("APCA-API-SECRET-KEY", sec)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            LAST_HEADERS.clear()
            LAST_HEADERS.update({k.lower(): v for k, v in r.headers.items()})
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read()[:400].decode("utf-8", "replace")
        if base == MD and e.code == 403 and "one device" in body.lower() and _retry:
            # Cloud egress IP changed since the last call. Wait out the lock, retry once.
            print(f"note: MarketData.app IP lock; waiting {LOCK_WAIT_S}s and retrying once", file=sys.stderr)
            import time
            time.sleep(LOCK_WAIT_S)
            return _get(base, path, params, _retry=False)
        raise SystemExit(f"HTTP {e.code} on {base}{path}: {body}  "
                         "(401 = token missing; 402/429 = out of credits; 403 = one-device IP lock)")


def credits():
    h = LAST_HEADERS
    g = lambda k: int(h[k]) if h.get(k, "").lstrip("-").isdigit() else None
    return {"limit": g("x-api-ratelimit-limit"), "remaining": g("x-api-ratelimit-remaining"),
            "consumed": g("x-api-ratelimit-consumed"), "reset": g("x-api-ratelimit-reset")}


def plan_request(budget, book_expiry):
    """Pick ONE request that fits the day's credits (~1 credit per contract).
    budget = daily credit limit from the last run's headers (None = unknown -> assume free plan)."""
    if budget is None or budget >= 10:       # historical pulls cost ~1 credit per 1,000 contracts: go wide
        return {"mode": "wide", "days": 21, "band": 0.08, "expiry": None, "strike_limit": None}
    # nearly out of credits: smallest useful pull
    return {"mode": "narrow", "days": 21, "band": 0.08, "expiry": book_expiry, "strike_limit": 40}


def fetch_chain(underlying, exp_lo, exp_hi, k_lo, k_hi):
    """Returns {symbol: {kind, K, expiry, bid, ask, iv_feed, quote_time}}."""
    out, token = {}, None
    while True:
        p = {"feed": "indicative", "limit": 1000,
             "expiration_date_gte": exp_lo.isoformat(), "expiration_date_lte": exp_hi.isoformat(),
             "strike_price_gte": f"{k_lo:.2f}", "strike_price_lte": f"{k_hi:.2f}"}
        if token:
            p["page_token"] = token
        js = _get(DATA, f"/v1beta1/options/snapshots/{underlying}", p)
        for sym, s in (js.get("snapshots") or {}).items():
            m = OCC.match(sym)
            if not m:
                continue
            q = s.get("latestQuote") or {}
            out[sym] = {"kind": m.group(3), "K": int(m.group(4)) / 1000.0,
                        "expiry": dt.datetime.strptime(m.group(2), "%y%m%d").date(),
                        "bid": float(q.get("bp") or 0), "ask": float(q.get("ap") or 0),
                        "quote_time": q.get("t"), "iv_feed": s.get("impliedVolatility")}
        token = js.get("next_page_token")
        if not token:
            return out


def fetch_open_interest(underlying, exp_lo, exp_hi, k_lo, k_hi):
    """{symbol: (open_interest, as_of)} from the trading API's contract list; {} if unavailable."""
    out, token = {}, None
    try:
        while True:
            p = {"underlying_symbols": underlying, "limit": 10000, "status": "active",
                 "expiration_date_gte": exp_lo.isoformat(), "expiration_date_lte": exp_hi.isoformat(),
                 "strike_price_gte": f"{k_lo:.2f}", "strike_price_lte": f"{k_hi:.2f}"}
            if token:
                p["page_token"] = token
            js = _get(TRADE, "/v2/options/contracts", p)
            for c in js.get("option_contracts") or []:
                if c.get("open_interest") not in (None, ""):
                    out[c["symbol"]] = (float(c["open_interest"]), c.get("open_interest_date"))
            token = js.get("next_page_token")
            if not token:
                return out
    except SystemExit as e:
        print(f"note: open interest unavailable ({e})", file=sys.stderr)
        return {}


def fetch_spot(symbol):
    js = _get(DATA, f"/v2/stocks/{symbol}/snapshot", {"feed": "iex"})
    t = (js.get("latestTrade") or {}).get("p")
    return float(t) if t else None


# ---------------------------------------------------------------- analysis
def usable(c):
    if c["ask"] <= 0 or c["bid"] < 0 or c["ask"] < c["bid"]:
        return False
    return True


def enrich(chain, spot, now):
    """Adds mid, width, own IV, delta, gamma to each usable contract, by expiry."""
    by_exp = {}
    for sym, c in chain.items():
        if not usable(c):
            continue
        T = years(c["expiry"], now)
        if T <= 0:
            continue
        c = dict(c, sym=sym, T=T, mid=(c["bid"] + c["ask"]) / 2, width=c["ask"] - c["bid"])
        c["wide"] = c["mid"] <= 0 or c["width"] / c["mid"] > WIDE
        c["iv"] = implied_vol(c["mid"], spot, c["K"], T, c["kind"])
        if c["iv"] is None:
            continue
        c["delta"], c["gamma"] = greeks(spot, c["K"], T, c["iv"], c["kind"])
        by_exp.setdefault(c["expiry"], []).append(c)
    return by_exp


def expiry_stats(rows, spot):
    calls = [c for c in rows if c["kind"] == "C" and not c["wide"]]
    puts = [c for c in rows if c["kind"] == "P" and not c["wide"]]
    otm = [c for c in calls if c["K"] >= spot] + [c for c in puts if c["K"] <= spot]
    if len(otm) < 4:
        return None
    atm = interp([c["K"] for c in otm], [c["iv"] for c in otm], spot)
    p25 = interp([-c["delta"] for c in puts], [c["iv"] for c in puts], 0.25) if puts else None
    c25 = interp([c["delta"] for c in calls], [c["iv"] for c in calls], 0.25) if calls else None
    # straddle at the strike nearest spot
    ks = sorted({c["K"] for c in rows}, key=lambda k: abs(k - spot))
    straddle = None
    for k in ks[:3]:
        cc = [c for c in rows if c["K"] == k and c["kind"] == "C"]
        pp = [c for c in rows if c["K"] == k and c["kind"] == "P"]
        if cc and pp:
            straddle = cc[0]["mid"] + pp[0]["mid"]
            break
    # skew slopes in the book's units: vol points per 1% out of the money
    def slope(side):
        pts = [(abs(math.log(spot / c["K"])) * 100, (c["iv"] - atm) * 100) for c in side
               if 0.5 <= abs(math.log(spot / c["K"])) * 100 <= 8]
        num = sum(x * y for x, y in pts)
        den = sum(x * x for x, _ in pts)
        return round(num / den, 3) if den else None
    widths = sorted(c["width"] / c["mid"] for c in otm if c["mid"] > 0)
    return {
        "atm_iv": round(atm * 100, 2),
        "iv_25d_put": round(p25 * 100, 2) if p25 else None,
        "iv_25d_call": round(c25 * 100, 2) if c25 else None,
        "skew_25d": round((p25 - c25) * 100, 2) if p25 and c25 else None,
        "put_skew_slope": slope([c for c in puts if c["K"] < spot]),
        "call_skew_slope": slope([c for c in calls if c["K"] > spot]),
        "implied_move_pct": round(straddle / spot * 100, 2) if straddle else None,
        "median_width_pct_of_mid": round(widths[len(widths) // 2] * 100, 1) if widths else None,
        "contracts_used": len(otm),
    }


def gamma_stats(by_exp, oi, spot, now, max_days=30):
    """Dealer gamma in $ per 1% SPY move, assuming dealers long calls / short puts."""
    rows = [c for e, cs in by_exp.items() if (e - now.date()).days <= max_days for c in cs if c["sym"] in oi]
    if not rows:
        return None

    def gex_at(S):
        tot = 0.0
        for c in rows:
            _, g = greeks(S, c["K"], c["T"], c["iv"], c["kind"])
            sign = 1 if c["kind"] == "C" else -1
            tot += sign * g * oi[c["sym"]][0] * 100 * S * S * 0.01
        return tot

    grid = [spot * (1 + i / 1000) for i in range(-60, 61, 2)]
    vals = [gex_at(s) for s in grid]
    flip = None
    for (s0, v0), (s1, v1) in zip(zip(grid, vals), zip(grid[1:], vals[1:])):
        if v0 == 0 or (v0 < 0) != (v1 < 0):
            flip = s0 + (s1 - s0) * (0 - v0) / (v1 - v0) if v1 != v0 else s0
            break
    by_k = {}
    for c in rows:
        by_k.setdefault((c["kind"], c["K"]), 0.0)
        by_k[(c["kind"], c["K"])] += oi[c["sym"]][0]
    cw = max((k for k in by_k if k[0] == "C"), key=lambda k: by_k[k], default=None)
    pw = max((k for k in by_k if k[0] == "P"), key=lambda k: by_k[k], default=None)
    dates = sorted({oi[c["sym"]][1] for c in rows if oi[c["sym"]][1]})
    return {
        "gex_usd_per_1pct": round(gex_at(spot)),
        "gamma_sign": "positive (moves tend to be damped)" if gex_at(spot) > 0 else "negative (moves tend to be amplified)",
        "flip_level": round(flip, 2) if flip else None,
        "call_wall": cw[1] if cw else None,
        "put_wall": pw[1] if pw else None,
        "oi_as_of": dates[-1] if dates else None,
        "assumption": "dealers long calls, short puts; open interest is prior day",
        "contracts_used": len(rows),
    }


def summarize(chain, oi, spot, now):
    by_exp = enrich(chain, spot, now)
    exps = {}
    for e in sorted(by_exp):
        s = expiry_stats(by_exp[e], spot)
        if s:
            exps[e.isoformat()] = dict(s, days=(e - now.date()).days)
    front = next(iter(exps.values()), None)
    return {
        "source": "Alpaca indicative feed (free; 15-min delayed, modified quotes)",
        "at": now.isoformat(timespec="minutes"),
        "spot": round(spot, 2),
        "expiries": exps,
        "fallback_skew": {"put": front["put_skew_slope"], "call": front["call_skew_slope"]} if front else None,
        "gamma": gamma_stats(by_exp, oi, spot, now) if oi else None,
        "note": "Derived numbers only; raw quotes are never stored or republished.",
    }


def price_legs(chain, legs, expiry, spot, now, atm_iv=None, skew=None):
    """legs [[qty, 'C'|'P', K]], qty>0 long. Per share. Fill = mid + half width per leg, against us."""
    T = years(expiry, now)
    mid = fill_in = fill_out = 0.0
    detail, src = [], "alpaca"
    for q, kind, K in legs:
        sym = next((s for s, c in chain.items()
                    if c["kind"] == kind and abs(c["K"] - K) < 1e-6 and c["expiry"] == expiry), None)
        c = chain.get(sym) if sym else None
        if c and usable(c) and c["ask"] > 0:
            m, h = (c["bid"] + c["ask"]) / 2, (c["ask"] - c["bid"]) / 2
            leg_src = "alpaca"
        else:
            iv = _model_iv(spot, K, atm_iv, skew)
            m, h, leg_src, src = bs(spot, K, T, iv, kind), 0.03, "model", "mixed" if src == "alpaca" else src
        mid += q * m
        fill_in += q * m + abs(q) * h    # opening: pay half the width on every leg
        fill_out += q * m - abs(q) * h   # closing: give up half the width again
        detail.append({"q": q, "kind": kind, "K": K, "mid": round(m, 3), "half_width": round(h, 3), "src": leg_src})
    return {"expiry": expiry.isoformat(), "mid": round(mid, 3), "open_fill": round(fill_in, 3),
            "close_fill": round(fill_out, 3), "source": src, "legs": detail}


def _model_iv(spot, K, atm_iv, skew):
    atm = atm_iv if atm_iv else 20.0
    ps, cs = (skew or {}).get("put") or MODEL_PUT_SKEW, (skew or {}).get("call") or MODEL_CALL_SKEW
    m = math.log(spot / K) * 100          # >0: strike below spot (puts OTM)
    v = atm + (ps if m > 0 else cs) * abs(m)
    return max(0.10, v / 100)


# ---------------------------------------------------------------- live entry points
NYSE_HOLIDAYS = {"2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
                 "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}


def is_session(d):
    return d.weekday() < 5 and d.isoformat() not in NYSE_HOLIDAYS


def prev_session(d):
    d -= dt.timedelta(days=1)
    while not is_session(d):
        d -= dt.timedelta(days=1)
    return d


def latest_free_session(now_utc):
    """Free/historical data for session D is released at 09:30 ET on the next session after D."""
    from zoneinfo import ZoneInfo
    et = now_utc.astimezone(ZoneInfo("America/New_York"))
    release = et.date()
    if not (is_session(release) and et.time() >= dt.time(9, 31)):
        release = prev_session(release)
    return prev_session(release)


def parity_spot(chain, T_of):
    """Spot from put-call parity at the strike where call and put mids are closest."""
    best = None
    for c in chain.values():
        if c["kind"] != "C" or not usable(c):
            continue
        p = next((x for x in chain.values() if x["kind"] == "P" and x["K"] == c["K"]
                  and x["expiry"] == c["expiry"] and usable(x)), None)
        if not p:
            continue
        cm, pm = (c["bid"] + c["ask"]) / 2, (p["bid"] + p["ask"]) / 2
        T = T_of(c["expiry"])
        if T <= 0:
            continue
        s = (cm - pm + c["K"] * math.exp(-RATE * T)) * math.exp(DIV * T)
        if best is None or abs(cm - pm) < best[0]:
            best = (abs(cm - pm), s)
    return best[1] if best else None


def fetch_marketdata(underlying, exp_lo, exp_hi, band, date=None, expiration=None, strike_limit=None):
    """MarketData.app chain (free plan = prior session, 24h delayed). Columnar JSON.
    Returns (chain, oi, spot, as_of). Field names per their docs; unverified until a live run."""
    # Billing (MarketData.app chain docs, 12 Nov 2026): live/delayed chains cost 1 credit per
    # contract (measured 26 Nov: ~2,040 for one wide pull); a historical pull with `date` costs
    # 1 credit per 1,000 contracts. Free data is historical anyway, so ALWAYS send `date`.
    date = date or latest_free_session(dt.datetime.now(dt.timezone.utc)).isoformat()
    p = {"expiration": expiration} if expiration else {"from": exp_lo.isoformat(), "to": exp_hi.isoformat()}
    p["range"] = "all"
    if strike_limit:
        p["strikeLimit"] = strike_limit
    if date:
        p["date"] = date
    js = _get(MD, f"/v1/options/chain/{underlying}/", p)
    if js.get("s") not in ("ok", None):
        raise SystemExit(f"MarketData.app: {js.get('s')} {js.get('errmsg', '')}")
    syms = js.get("optionSymbol") or []
    col = lambda k, i, d=None: (js.get(k) or [d] * len(syms))[i]
    spot = next((float(x) for x in (js.get("underlyingPrice") or []) if x), None)
    close_t = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(21, 0), tzinfo=dt.timezone.utc)
    chain, oi, stamps = {}, {}, []
    for i, sym in enumerate(syms):
        m = OCC.match(sym)
        if not m:
            continue
        K = int(m.group(4)) / 1000.0
        chain[sym] = {"kind": m.group(3), "K": K,
                      "expiry": dt.datetime.strptime(m.group(2), "%y%m%d").date(),
                      "bid": float(col("bid", i, 0) or 0), "ask": float(col("ask", i, 0) or 0),
                      "quote_time": col("updated", i), "iv_feed": col("iv", i)}
        o = col("openInterest", i)
        if o not in (None, ""):
            oi[sym] = (float(o), None)
        if col("updated", i):
            stamps.append(int(col("updated", i)))
    as_of = dt.datetime.fromtimestamp(max(stamps), dt.timezone.utc) if stamps else close_t
    if not spot:   # historical rows may omit it: use put-call parity, and say so
        spot = parity_spot(chain, lambda e: years(e, as_of))
        if spot:
            print("note: spot from put-call parity (no underlyingPrice in response)", file=sys.stderr)
    if not spot:
        raise SystemExit("MarketData.app returned no usable underlying price; stop rather than guess.")
    chain = {k: v for k, v in chain.items() if abs(math.log(v["K"] / spot)) <= band}
    oi = {k: (v[0], as_of.date().isoformat()) for k, v in oi.items() if k in chain}
    return chain, oi, spot, as_of


def live(args):
    now = dt.datetime.now(dt.timezone.utc)
    lo_e, hi_e = now.date(), now.date() + dt.timedelta(days=args.days)
    if args.source == "marketdata":
        if args.budget is not None or args.auto:
            p = plan_request(args.budget, getattr(args, "expiry", None) or _next_weekly(now.date()))
            args.band, args.strike_limit = p["band"], p["strike_limit"]
            lo_e, hi_e = now.date(), now.date() + dt.timedelta(days=max(p["days"], args.days))
            if p["expiry"]:
                args.expiry = p["expiry"]
            args.plan = p["mode"]
        pull_exp = getattr(args, "expiry", None) if getattr(args, "plan", "manual") != "wide" else None
        chain, oi, spot, as_of = fetch_marketdata("SPY", lo_e, hi_e, args.band, args.date,
                                                  pull_exp, args.strike_limit)
        if not chain:
            raise SystemExit("MarketData.app returned an empty chain; stop rather than guess.")
        return as_of, spot, chain, oi        # value everything at the quotes' own time
    spot = fetch_spot("SPY")
    if not spot:
        raise SystemExit("No SPY price from Alpaca; stop rather than guess.")
    k_lo, k_hi = spot * (1 - args.band), spot * (1 + args.band)
    chain = fetch_chain("SPY", lo_e, hi_e, k_lo, k_hi)
    if not chain:
        raise SystemExit("Alpaca returned an empty chain; stop rather than guess.")
    return now, spot, chain, fetch_open_interest("SPY", lo_e, hi_e, k_lo, k_hi)


def _next_weekly(d):
    """Book rule: nearest weekly (Friday) expiry at least 3 trading days out (holidays ignored)."""
    x, td = d, 0
    while True:
        x += dt.timedelta(days=1)
        if x.weekday() < 5:
            td += 1
        if td >= 3 and x.weekday() == 4:
            return x.isoformat()


def cmd_summary(args):
    args.book_items = []
    if args.book:
        raw = open(args.book).read() if os.path.exists(args.book) else args.book
        args.book_items = json.loads(raw)
        far = max((dt.date.fromisoformat(i["expiry"]) for i in args.book_items), default=None)
        if far:
            args.days = max(args.days, (far - dt.date.today()).days + 1)
    now, spot, chain, oi = live(args)
    out = summarize(chain, oi, spot, now)
    if args.source == "marketdata":
        out["source"] = "MarketData.app (prior session's closing quotes)"
    out["credits"] = credits()
    out["plan"] = getattr(args, "plan", "manual")
    if out["plan"] == "narrow":
        out["gamma"] = None   # one expiry, near strikes only: too partial to call a gamma level
    if args.legs:
        f = next(iter(out["expiries"].values()), {})
        exp = dt.date.fromisoformat(args.expiry) if args.expiry else min(c["expiry"] for c in chain.values())
        out["price"] = price_legs(chain, json.loads(args.legs), exp, spot, now,
                                  atm_iv=f.get("atm_iv"), skew=out.get("fallback_skew"))
    for item in getattr(args, "book_items", []):
        exp = dt.date.fromisoformat(item["expiry"])
        e = out["expiries"].get(item["expiry"]) or next(iter(out["expiries"].values()), {})
        if exp < now.date():
            out.setdefault("book", {})[item["id"]] = {"skipped": "expired before these quotes"}
            continue
        out.setdefault("book", {})[item["id"]] = price_legs(
            chain, item["legs"], exp, spot, now, atm_iv=e.get("atm_iv"), skew=out.get("fallback_skew"))
    print(json.dumps(out, indent=1, default=str))


def cmd_price(args):
    now, spot, chain, _ = live(args)
    expiry = dt.date.fromisoformat(args.expiry)
    s = summarize(chain, {}, spot, now)
    e = s["expiries"].get(args.expiry) or next(iter(s["expiries"].values()), {})
    out = price_legs(chain, json.loads(args.legs), expiry, spot, now,
                     atm_iv=e.get("atm_iv"), skew=s.get("fallback_skew"))
    out["spot"] = round(spot, 2)
    out["quotes_as_of"] = now.isoformat(timespec="minutes")
    print(json.dumps(out, indent=1))


# ---------------------------------------------------------------- self-test (synthetic, offline)
def _synthetic(spot, now, atm=0.20, put_slope=0.9, call_slope=0.3, width=0.04):
    chain, oi = {}, {}
    for d in (7, 14, 28):
        e = now.date() + dt.timedelta(days=d)
        T = years(e, now)
        for k in range(int(spot * 0.9), int(spot * 1.1) + 1):
            for kind in "CP":
                m = math.log(spot / k) * 100
                iv = max(0.05, atm + (put_slope * m if m > 0 else call_slope * m) / 100)
                p = bs(spot, k, T, iv, kind)
                if p < 0.05:
                    continue
                sym = f"SPY{e:%y%m%d}{kind}{int(k * 1000):08d}"
                chain[sym] = {"kind": kind, "K": float(k), "expiry": e, "bid": max(0.01, p - width / 2),
                              "ask": p + width / 2, "quote_time": None, "iv_feed": None}
                oi[sym] = (1000.0 if kind == "C" else 1500.0, "synthetic")
    return chain, oi


def cmd_selftest(_):
    now = dt.datetime(2026, 11, 27, 15, 0, tzinfo=dt.timezone.utc)
    spot = 700.0
    chain, oi = _synthetic(spot, now)
    s = summarize(chain, oi, spot, now)
    f = next(iter(s["expiries"].values()))
    ok = []
    ok.append(("ATM IV ~20", abs(f["atm_iv"] - 20) < 0.6, f["atm_iv"]))
    ok.append(("put slope ~0.9", f["put_skew_slope"] and abs(f["put_skew_slope"] - 0.9) < 0.12, f["put_skew_slope"]))
    ok.append(("call slope ~-0.3 sign", f["call_skew_slope"] is not None and f["call_skew_slope"] < 0, f["call_skew_slope"]))
    ok.append(("put skew > 0", (f["skew_25d"] or 0) > 0, f["skew_25d"]))
    ok.append(("gamma computed", s["gamma"] is not None, s["gamma"] and s["gamma"]["gex_usd_per_1pct"]))
    e7 = now.date() + dt.timedelta(days=7)
    p = price_legs(chain, [[1, "P", 690], [-1, "P", 680]], e7, spot, now)
    ok.append(("spread priced from quotes", p["source"] == "alpaca" and 0 < p["mid"] < 10, p["mid"]))
    ok.append(("fills straddle mid", p["close_fill"] < p["mid"] < p["open_fill"], (p["close_fill"], p["open_fill"])))
    pm = price_legs(chain, [[1, "P", 690], [-1, "P", 123]], e7, spot, now, atm_iv=20)
    ok.append(("missing leg falls back to model", pm["source"] == "mixed", pm["source"]))
    iv_c = _model_iv(spot, 721, 20.0, s["fallback_skew"]) * 100
    iv_p = _model_iv(spot, 679, 20.0, s["fallback_skew"]) * 100
    ok.append(("fallback skew: OTM call IV < ATM < OTM put IV", iv_c < 20 < iv_p, (round(iv_c, 2), round(iv_p, 2))))
    # MarketData.app columnar parser on a tiny fake payload (offline)
    global _get
    real = _get
    _get = lambda *a, **k: {"s": "ok", "optionSymbol": ["SPY261204P00690000", "SPY261204C00710000"],
                            "underlyingPrice": [700.0, 700.0], "bid": [2.0, 1.5], "ask": [2.1, 1.6],
                            "openInterest": [5000, 4000], "iv": [0.21, 0.18], "updated": [1795640400, 1795640400]}
    try:
        ch, o, sp, at = fetch_marketdata("SPY", now.date(), now.date() + dt.timedelta(days=30), 0.12)
    finally:
        _get = real
    ok.append(("marketdata parser", len(ch) == 2 and sp == 700.0 and o["SPY261204P00690000"][0] == 5000,
               (len(ch), sp)))
    ok.append(("planner: trial -> wide, free -> narrow",
               plan_request(100000, "2026-12-04")["mode"] == "wide" and plan_request(100, "2026-12-04")["mode"] == "wide"
               and plan_request(3, "2026-12-04")["mode"] == "narrow", None))
    ok.append(("next weekly >= 3 trading days", _next_weekly(dt.date(2026, 11, 26)) == "2026-12-04"
               and _next_weekly(dt.date(2026, 11, 23)) == "2026-11-27", _next_weekly(dt.date(2026, 11, 26))))
    now_t = lambda y, mo, d, h, mi: dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc)
    ok.append(("latest free session", latest_free_session(now_t(2026, 11, 26, 5, 0)).isoformat() == "2026-11-24"
               and latest_free_session(now_t(2026, 11, 27, 15, 0)).isoformat() == "2026-11-25"
               and latest_free_session(now_t(2026, 11, 30, 14, 0)).isoformat() == "2026-11-25",
               [latest_free_session(now_t(2026, 11, 27, 15, 0)).isoformat()]))
    ok.append(("parity spot", abs((parity_spot(chain, lambda e: years(e, now)) or 0) - spot) < 0.5,
               parity_spot(chain, lambda e: years(e, now))))
    for name, good, val in ok:
        print(("PASS " if good else "FAIL ") + name + f"  [{val}]")
    print("SYNTHETIC test data only, not market data.")
    sys.exit(0 if all(g for _, g, _ in ok) else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("summary", "price"):
        sp = sub.add_parser(name)
        sp.add_argument("--days", type=int, default=45)
        sp.add_argument("--band", type=float, default=0.12)
        sp.add_argument("--source", choices=["marketdata", "alpaca"], default="marketdata")
        sp.add_argument("--date", help="MarketData.app: session date YYYY-MM-DD (default: latest allowed)")
        sp.add_argument("--budget", type=int, default=None,
                        help="daily credit limit from the last run (credits.limit); picks wide or narrow")
        sp.add_argument("--auto", action="store_true", help="plan the request automatically (unknown budget = free plan)")
        sp.add_argument("--strike-limit", type=int, default=None,
                        help="MarketData.app: only this many strikes around the money (saves credits)")
        sp.add_argument("--expiry", required=(name == "price"),
                        help="one expiry only (summary: optional; saves credits)")
        if name == "summary":
            sp.add_argument("--book", help='JSON list (or file) [{"id","expiry","legs"}]: price every '
                            'paper-book structure from the same single request')
        sp.add_argument("--legs", required=(name == "price"),
                        help='[[qty,"C"|"P",strike],...]; with summary, priced from the same request')
    sub.add_parser("selftest")
    a = ap.parse_args()
    {"summary": cmd_summary, "price": cmd_price, "selftest": cmd_selftest}[a.cmd](a)


if __name__ == "__main__":
    main()
