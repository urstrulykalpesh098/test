"""Ten defined-risk SPY option trades for the week of 9-13 Nov 2026, tested
against the 604 simulated weeks in analyses/output/week_nov9.json.

IMPORTANT LIMITS
  * No live or historical option chain was available in this environment
    (Alpha Vantage chains are a paid endpoint; FMP has no options). Every
    option price here is a MODEL ESTIMATE from Black-Scholes with the
    volatility assumptions below, anchored to the real VIX (25.64).
  * The simulation is uncalibrated. "Edge" below means the simulation's
    distribution disagrees with the option model's. It is not evidence the
    real market is mispriced.
  * Each trade carries a hard check: the MAX DEBIT that keeps reward:risk
    at 1:2 or better. Compare it with the live quote before doing anything.

Run:  python analyses/options_nov9.py
Out:  analyses/output/options_nov9.json
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from marketsim.analysis import _pct  # noqa: E402

SIM = json.loads((ROOT / "analyses" / "output" / "week_nov9.json").read_text())
SPY_PER_SPX = 734.06 / 7353.73        # SPY/SPX on the 5 Nov close (Morning Brief + Week report)
RATE, DIV = 0.039, 0.012              # fed funds midpoint; approximate SPY yield
BUDGET = 2000.0
LEG_SLIPPAGE = 0.03                   # paid over model mid, per option leg
VIX = 25.64
PUT_SKEW, CALL_SKEW = 0.9, 0.3        # vol points per 1% out of the money (assumption)
MA200 = SIM["meta"]["ma200"]
DAYS_TO_EXP = {"mon_open": 5, "mon_close": 4, "tue_close": 3, "wed_close": 2}   # to Fri 13 Nov close

N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, iv, kind):
    if T <= 0:
        return max(0.0, S - K) if kind == "C" else max(0.0, K - S)
    d1 = (math.log(S / K) + (RATE - DIV + iv * iv / 2) * T) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)
    if kind == "C":
        return S * math.exp(-DIV * T) * N(d1) - K * math.exp(-RATE * T) * N(d2)
    return K * math.exp(-RATE * T) * N(-d2) - S * math.exp(-DIV * T) * N(-d1)


def iv_for(S, K, atm):
    m = math.log(S / K) * 100  # >0: strike below spot
    v = atm + (PUT_SKEW * m if m > 0 else CALL_SKEW * m)
    return max(0.10, v / 100)


def atm_iv(when, run_ret, cpi=None, crwv=None):
    """ATM implied vol at entry (vol points). Assumption, stated in the report."""
    base = VIX
    if when in ("tue_close", "wed_close"):
        base = {"hot": 27.0, "inline": 22.0, "cool": 20.0}[cpi]       # CPI event passes; level resets
    if when == "wed_close":
        base += 2.0 if crwv == "bad" else -1.5
    return max(12.0, base - 2.5 * run_ret * 100)                       # vol rises as the market falls


def price_structure(legs, S, T, atm):
    """legs: [(qty, kind, K)] qty>0 long. Returns net debit per share incl. slippage."""
    mid = sum(q * bs(S, K, T, iv_for(S, K, atm), kd) for q, kd, K in legs)
    return mid + LEG_SLIPPAGE * sum(abs(q) for q, _, _ in legs)


def payoff(legs, S_T):
    return sum(q * (max(0.0, S_T - K) if kd == "C" else max(0.0, K - S_T)) for q, kd, K in legs)


def max_gain_loss(legs, debit):
    grid = [x / 4 for x in range(4 * 600, 4 * 860)]
    pays = [payoff(legs, s) for s in grid]
    return max(pays) - debit, debit - min(pays)


def spy(spx):
    return spx * SPY_PER_SPX


# ---------------------------------------------------------------- the trades
FRI = spy(SIM["meta"]["friday_close"])
R = lambda x: float(round(x))


def fixed(legs):
    return lambda S: legs


TRADES = [
    {"id": "T1", "name": "200-day break, put spread", "when": "mon_open",
     "rule": "Monday at the open, no condition",
     "thesis": "A close below the rising 200-day (S&P ~7,325, SPY ~731) is likely in 81% of simulated weeks; trend followers then sell Tue-Fri (6 Nov briefing).",
     "legs": fixed([(1, "P", 730), (-1, "P", 720)])},
    {"id": "T2", "name": "Confirmed 200-day break, put spread", "when": "mon_close",
     "rule": "Monday at the close, only if the S&P closes below 7,325",
     "thesis": "Wait for the trigger itself, then own the trend followers' selling into Friday.",
     "cond": lambda run: run["closes"][0] < MA200,
     "legs": lambda S: [(1, "P", R(S - 5)), (-1, "P", R(S - 15))]},
    {"id": "T3", "name": "Bad-path landing, put butterfly", "when": "mon_open",
     "rule": "Monday at the open, no condition",
     "thesis": "The hot-CPI / CoreWeave-bad paths cluster around S&P 7,110-7,230 by Friday (SPY 710-722).",
     "legs": fixed([(1, "P", 725), (-2, "P", 715), (1, "P", 705)])},
    {"id": "T4", "name": "Hot-CPI follow-through, put spread", "when": "tue_close",
     "rule": "Tuesday at the close, only after a hot CPI",
     "thesis": "Hot CPI is the largest single input: median Friday 7,170. Trend followers and vol funds keep selling after it.",
     "cond": lambda run: run["cpi"] == "hot",
     "legs": lambda S: [(1, "P", R(S - 6)), (-1, "P", R(S - 16))]},
    {"id": "T5", "name": "Cool-CPI follow-through, call spread", "when": "tue_close",
     "rule": "Tuesday at the close, only after a cool CPI",
     "thesis": "Cool CPI takes the December hike out of the price; median Friday 7,475 and value buyers keep lifting it.",
     "cond": lambda run: run["cpi"] == "cool",
     "legs": lambda S: [(1, "C", R(S + 5)), (-1, "C", R(S + 13))]},
    {"id": "T6", "name": "Relief rally, call spread", "when": "mon_open",
     "rule": "Monday at the open, no condition",
     "thesis": "Cheap upside to the cool-CPI + CoreWeave-good paths (median 7,556) and the Iran de-escalation tail the Proactive Report calls most underweighted.",
     "legs": fixed([(1, "C", 745), (-1, "C", 755)])},
    {"id": "T7", "name": "Good-path landing, call butterfly", "when": "mon_open",
     "rule": "Monday at the open, no condition",
     "thesis": "Targets the best paths' Friday cluster around SPY 750-756.",
     "legs": fixed([(1, "C", 745), (-2, "C", 755), (1, "C", 765)])},
    {"id": "T8", "name": "CoreWeave contagion, put spread", "when": "wed_close",
     "rule": "Wednesday at the close, only if CoreWeave disappointed",
     "thesis": "A bad CoreWeave print spreads AI-credit fear while trend followers are already selling.",
     "cond": lambda run: run["crwv"] == "bad",
     "legs": lambda S: [(1, "P", R(S - 5)), (-1, "P", R(S - 13))]},
    {"id": "T9", "name": "Broken-wing put butterfly", "when": "mon_open",
     "rule": "Monday at the open, no condition",
     "thesis": "Pays most if SPY drifts to ~720 (S&P ~7,215); the skipped strike keeps the cost low.",
     "legs": fixed([(1, "P", 732), (-2, "P", 720), (1, "P", 705)])},
    {"id": "T10", "name": "Failed-break reversal, call spread", "when": "mon_close",
     "rule": "Monday at the close, only if the S&P held above 7,325 all day and closed up",
     "thesis": "If the 200-day holds and Monday rallies, dealers' short gamma helps the bounce and the forced sellers look done.",
     "cond": lambda run: run["lows"][0] > MA200 and run["closes"][0] > SIM["meta"]["friday_close"],
     "legs": lambda S: [(1, "C", R(S + 7)), (-1, "C", R(S + 15))]},
]


def runs():
    for key, p in SIM["paths"].items():
        for closes, lows in zip(p["run_closes"], p["run_lows"]):
            yield {"cpi": p["cpi"], "crwv": p["crwv"], "forced": p["forced"], "closes": closes, "lows": lows}


ENTRY_IDX = {"mon_close": 0, "tue_close": 1, "wed_close": 2}


def evaluate(tr, price_mult=1.0):
    pnl, rr_list, debits, triggered, total = [], [], [], 0, 0
    beyond_sim, beyond_mkt = [], []
    first_legs = None
    for run in runs():
        total += 1
        if "cond" in tr and not tr["cond"](run):
            continue
        triggered += 1
        if tr["when"] == "mon_open":
            S = FRI
            ret = 0.0
        else:
            S = spy(run["closes"][ENTRY_IDX[tr["when"]]])
            ret = S / FRI - 1
        T = DAYS_TO_EXP[tr["when"]] / 252
        legs = tr["legs"](S)
        first_legs = first_legs or legs
        debit = price_structure(legs, S, T, atm_iv(tr["when"], ret, run["cpi"], run["crwv"])) * price_mult
        gain, loss = max_gain_loss(legs, debit)
        S_T = spy(run["closes"][4])
        q, kd, K = max(legs, key=lambda l: (l[0] > 0, -abs(l[2] - S)))   # nearest long leg
        a = atm_iv(tr["when"], ret, run["cpi"], run["crwv"])
        iv = iv_for(S, K, a)
        d2 = (math.log(S / K) + (RATE - DIV - iv * iv / 2) * T) / (iv * math.sqrt(T))
        beyond_mkt.append(N(-d2) if kd == "P" else N(d2))
        beyond_sim.append(1.0 if (S_T < K if kd == "P" else S_T > K) else 0.0)
        pnl.append((payoff(legs, S_T) - debit) / loss)  # per $1 of maximum risk
        rr_list.append(gain / loss)
        debits.append(debit)
    if not pnl:
        return None
    # one representative ticket at the typical entry
    S0 = FRI if tr["when"] == "mon_open" else spy(statistics.median(
        r["closes"][ENTRY_IDX[tr["when"]]] for r in runs() if "cond" not in tr or tr["cond"](r)))
    legs0 = tr["legs"](S0)
    dbt = statistics.median(debits)
    gain, loss = max_gain_loss(legs0, dbt)
    width_gain = gain + dbt  # maximum payoff of the structure
    contracts = int(BUDGET // (loss * 100)) if loss > 0 else 0
    return {
        "trigger_rate": triggered / total, "n": len(pnl),
        "p_beyond_long_strike_options": statistics.mean(beyond_mkt),
        "p_beyond_long_strike_sim": statistics.mean(beyond_sim),
        "legs": legs0, "spot_at_entry": round(S0, 2),
        "debit": round(dbt, 2), "max_gain": round(gain, 2), "max_loss": round(loss, 2),
        "reward_risk": round(gain / loss, 2) if loss else None,
        "max_debit_for_1to2": round(width_gain / 3, 2),
        "contracts_for_budget": contracts,
        "cash_at_risk": round(contracts * loss * 100, 0), "cash_max_gain": round(contracts * gain * 100, 0),
        "p_profit": sum(x > 0 for x in pnl) / len(pnl),
        "p_max_gain": sum(x >= 0.98 * gain / loss for x in pnl) / len(pnl),
        "p_lose_all": sum(x <= -0.98 for x in pnl) / len(pnl),
        "ev_per_dollar_risked": statistics.mean(pnl),
        "ev_p05": _pct(pnl, 0.05), "ev_median": statistics.median(pnl),
    }


def main():
    out = {"meta": {"spy_friday": round(FRI, 2), "spy_ma200": round(spy(MA200), 2), "vix": VIX,
                    "put_skew": PUT_SKEW, "call_skew": CALL_SKEW, "slippage_per_leg": LEG_SLIPPAGE,
                    "budget": BUDGET, "runs": sum(1 for _ in runs()), "expiry": "2026-11-13"},
           "trades": []}
    for tr in TRADES:
        base = evaluate(tr)
        rich = evaluate(tr, price_mult=1.25)   # robustness: options cost 25% more than the model says
        cheap = evaluate(tr, price_mult=0.85)
        row = {k: tr[k] for k in ("id", "name", "when", "rule", "thesis")}
        row.update(base)
        row["ev_if_25pct_richer"] = rich["ev_per_dollar_risked"]
        row["ev_if_15pct_cheaper"] = cheap["ev_per_dollar_risked"]
        row["passes_1to2"] = base["reward_risk"] is not None and base["reward_risk"] >= 2.0
        out["trades"].append(row)
    ok = [t for t in out["trades"] if t["passes_1to2"]]
    out["ranking"] = [t["id"] for t in sorted(ok, key=lambda t: (t["ev_if_25pct_richer"] > 0, t["ev_per_dollar_risked"]), reverse=True)]
    dest = ROOT / "analyses" / "output" / "options_nov9.json"
    dest.write_text(json.dumps(out, indent=1))
    f = lambda x: f"{x:+.2f}"
    print(f"SPY Fri {out['meta']['spy_friday']}  200d {out['meta']['spy_ma200']}")
    for t in out["trades"]:
        legs = " ".join(f"{'+' if q > 0 else ''}{q}{k}{int(K)}" for q, k, K in t["legs"])
        print(f"{t['id']:>3} {t['name'][:34]:<34} trig {t['trigger_rate']:.0%} | {legs:<22} debit {t['debit']:.2f} "
              f"R:R {t['reward_risk']} maxdebit {t['max_debit_for_1to2']} x{t['contracts_for_budget']} risk ${t['cash_at_risk']:.0f} "
              f"| gap mkt {t['p_beyond_long_strike_options']:.0%} sim {t['p_beyond_long_strike_sim']:.0%} | P(win) {t['p_profit']:.0%} P(max) {t['p_max_gain']:.0%} EV/$ {f(t['ev_per_dollar_risked'])} rich {f(t['ev_if_25pct_richer'])}")
    print("ranking", out["ranking"])


if __name__ == "__main__":
    main()
