"""Week of 9-13 Nov 2026: all reports combined into one simulation.

Five sessions (5 x 390 one-minute ticks) starting from Friday 6 Nov's real
close, with the week's dated catalysts and three open questions branched:

  CPI (Tue 8:30)           hot / in line / cool           30% / 45% / 25%  (assumption)
  CoreWeave (Tue, 5pm)     bad / good, felt Wed open      50% / 50%        (assumption)
  Forced selling           still ahead / mostly done      50% / 50%        (the reports' own open question)

= 12 paths. Runs are allocated to paths in proportion to their probability, so
pooled statistics are probability-weighted.

Mechanisms and levels come from the user's reports:
  * dealers short gamma below the ~7,667 flip, long gamma above it   (6 Nov briefing)
  * vol-target de-leveraging over 1-10 sessions, size disputed         (6 Nov briefing / Proactive report)
  * trend followers' 200-day signal still long, average ~7,325 rising ~2.2 pts/session (6 Nov briefing)
  * leveraged ETFs rebalance at every close                            (Mechanism School)
Real closes from FMP (analyses/data/spx_daily.csv).

Run:  python analyses/week_nov9.py [--runs 600] [--workers N]
Out:  analyses/output/week_nov9.json
"""
from __future__ import annotations

import argparse
import copy
import itertools
import json
import math
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analyses"))

from marketsim.agents import AGENT_TYPES  # noqa: E402
from marketsim.analysis import _pct  # noqa: E402
from marketsim.engine import run_scenario  # noqa: E402
from marketsim.scenario import Scenario  # noqa: E402
import monday_nov9 as mon  # noqa: E402  (shared calibration, levels and cast)

DAY = mon.DAY
DAYS = ["Mon 9", "Tue 10", "Wed 11", "Thu 12", "Fri 13"]
TICKS = DAY * len(DAYS)
SCALE = mon.SCALE
FRI = mon.FRIDAY_CLOSE
GAMMA_FLIP = 7667.0
MA200_SLOPE = 2.2  # points per session (6 Nov briefing)

CPI = {
    "hot":    {"label": "Hot CPI", "p": 0.30, "detail": "Core above consensus, wages already hot: December hike near fully priced",
               "ev": {"fundamental_change": -0.016, "sentiment": -0.6, "fundamental_vol": 1.5 * mon.DAILY_IMPLIED / math.sqrt(DAY), "duration": 2 * DAY},
               "ppi": {"fundamental_change": -0.003, "sentiment": -0.15}},
    "inline": {"label": "CPI in line", "p": 0.45, "detail": "No new information before the 9 Dec meeting",
               "ev": {"fundamental_change": 0.002, "sentiment": 0.1}, "ppi": None},
    "cool":   {"label": "Cool CPI", "p": 0.25, "detail": "Oil's slide shows up; December hike odds drop for the first time",
               "ev": {"fundamental_change": 0.013, "sentiment": 0.5}, "ppi": {"fundamental_change": 0.003, "sentiment": 0.15}},
}
CRWV = {
    "bad":  {"label": "CoreWeave disappoints", "p": 0.5, "detail": "Interest cost over guide, delivery slips: AI-credit fear spreads",
             "ev": {"fundamental_change": -0.009, "sentiment": -0.45, "mm_stress": 0.2, "duration": 60}},
    "good": {"label": "CoreWeave reassures", "p": 0.5, "detail": "Backlog converts, financing holds: the weakest credit in the trade steadies",
             "ev": {"fundamental_change": 0.006, "sentiment": 0.3}},
}
FORCED = {
    "ahead": {"label": "Forced selling still ahead", "p": 0.5,
              "detail": "Vol-target funds cut 20% over 3 sessions; dealers deeply short gamma",
              "vol_target": {"target_fraction": 0.80, "spread_days": 3}, "gamma": 160},
    "done":  {"label": "Forced selling mostly done", "p": 0.5,
              "detail": "Red team's view: exposure already cut; only 5% left over 2 sessions",
              "vol_target": {"target_fraction": 0.95, "spread_days": 2}, "gamma": 70},
}


def path_key(c, w, f):
    return f"{c}|{w}|{f}"


def build(c, w, f) -> Scenario:
    pop = copy.deepcopy(mon.POPULATION)
    for k in ("dealer_gamma", "vol_target", "leveraged_etf"):
        pop[k]["params"]["day_ticks"] = DAY
    pop["dealer_gamma"]["params"].update({"gamma": FORCED[f]["gamma"], "flip": GAMMA_FLIP / SCALE})
    pop["vol_target"]["params"].update(FORCED[f]["vol_target"])
    pop["cta_trend"] = {"count": 3, "cash": 300_000, "shares": 2_000,
                        "params": {"level": mon.MA200 / SCALE, "level_slope": MA200_SLOPE / SCALE,
                                   "short_fraction": 0.5, "exec_days": 2, "buffer": 0.003, "day_ticks": DAY}}
    events = [
        {"tick": 0, "headline": "Mon open: Korea suspends its margin rule, Taiwan caps short sales; China tariff exclusions expire tonight",
         "sentiment": -0.05},
        {"tick": DAY, "headline": f"Tue 8:30: {CPI[c]['label']}", **CPI[c]["ev"]},
        {"tick": 2 * DAY, "headline": f"Wed open: {CRWV[w]['label']} (reported Tue 5pm)", **CRWV[w]["ev"]},
        {"tick": 3 * DAY, "headline": "Thu: Applied Materials and Cisco read-through; Nebius before the open", "sentiment": 0.0},
    ]
    if CPI[c]["ppi"]:
        events.append({"tick": 4 * DAY, "headline": "Fri 8:30: PPI confirms CPI", **CPI[c]["ppi"]})
    else:
        events.append({"tick": 4 * DAY, "headline": "Fri 8:30: PPI in line", "sentiment": 0.0})
    return Scenario.from_dict({
        "name": f"week_{c}_{w}_{f}", "description": "", "ticks": TICKS, "initial_price": 100.0,
        "fundamental": {"vol": mon.DAILY_IMPLIED / math.sqrt(DAY), "drift": 0.0},
        "sentiment": {"decay": 0.995, "feedback": 8.0},
        "population": pop, "events": events,
    })


def summarise(run):
    """Everything we keep from one run (runs themselves stay in the worker)."""
    s = run.series
    price = s["price"]
    closes = [price[(d + 1) * DAY - 1] * SCALE for d in range(len(DAYS))]
    lows = [min(price[d * DAY:(d + 1) * DAY]) * SCALE for d in range(len(DAYS))]
    flows = {k: [sum(v[d * DAY:(d + 1) * DAY]) for d in range(len(DAYS))] for k, v in run.flows.items()}
    vols = [sum(s["volume"][d * DAY:(d + 1) * DAY]) for d in range(len(DAYS))]
    rets = {}
    for kind in run.flows:
        g = [a for a in run.agents if a.kind == kind]
        start = sum(a.initial_wealth(100.0) for a in g)
        rets[kind] = sum(a.wealth(run.final_price) for a in g) / start - 1 if start > 0 else 0.0
    cta = [a for a in run.agents if a.kind == "cta_trend"]
    return {
        "seed": run.seed, "closes": closes, "lows": lows, "flows": flows, "vols": vols, "rets": rets,
        "cta_flipped": any(a.flips for a in cta),
        "bars": [round(price[i] * SCALE, 2) for i in range(4, TICKS, 5)],          # 5-minute closes
        "fair": [round(s["fundamental"][i] * SCALE, 2) for i in range(4, TICKS, 5)],
        "bar_flows": {k: [sum(v[i - 4:i + 1]) for i in range(4, TICKS, 5)] for k, v in run.flows.items()},
        "bar_vol": [sum(s["volume"][i - 4:i + 1]) for i in range(4, TICKS, 5)],
        "events": [{"t": e["tick"] // 5, "headline": e["headline"]} for e in run.events],
    }


def work(args):
    c, w, f, seed = args
    return path_key(c, w, f), summarise(run_scenario(build(c, w, f), seed))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=600)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    a = ap.parse_args()

    paths = list(itertools.product(CPI, CRWV, FORCED))
    prob = {path_key(*p): CPI[p[0]]["p"] * CRWV[p[1]]["p"] * FORCED[p[2]]["p"] for p in paths}
    alloc = {k: max(16, round(a.runs * v)) for k, v in prob.items()}
    # Common random numbers: run i of every path uses the same seed, so the
    # market noise is identical across paths and differences come from the factors.
    jobs = [(c, w, f, 20000 + i) for (c, w, f) in paths for i in range(alloc[path_key(c, w, f)])]
    print(f"{len(jobs)} runs over {len(paths)} paths with {a.workers} workers", file=sys.stderr)
    results = {k: [] for k in prob}
    with ProcessPoolExecutor(a.workers) as ex:
        for i, (k, r) in enumerate(ex.map(work, jobs, chunksize=4), 1):
            results[k].append(r)
            if i % 50 == 0:
                print(f"  {i}/{len(jobs)}", file=sys.stderr)

    def stats(rs, weights=None):
        fri = [r["closes"][-1] for r in rs]
        lows = [min(r["lows"]) for r in rs]
        out = {
            "n": len(rs),
            "fri_close": {str(q): round(_pct(fri, q), 1) for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
            "fri_return_median": statistics.median(fri) / FRI - 1,
            "week_low": {str(q): round(_pct(lows, q), 1) for q in (0.05, 0.5)},
            "p_up_week": sum(x > FRI for x in fri) / len(rs),
            "p_close_below_thu_low": sum(x < mon.THURSDAY_LOW for x in fri) / len(rs),
            "p_any_close_below_200d": sum(any(c < mon.MA200 + MA200_SLOPE * d for d, c in enumerate(r["closes"])) for r in rs) / len(rs),
            "p_cta_flip": sum(r["cta_flipped"] for r in rs) / len(rs),
            "p_above_gamma_flip": sum(max(r["closes"]) > GAMMA_FLIP for r in rs) / len(rs),
            "p_down_5pct": sum(x < FRI * 0.95 for x in fri) / len(rs),
            "daily_close_median": [round(statistics.median(r["closes"][d] for r in rs), 1) for d in range(len(DAYS))],
            "daily_close_p05": [round(_pct([r["closes"][d] for r in rs], 0.05), 1) for d in range(len(DAYS))],
            "daily_close_p95": [round(_pct([r["closes"][d] for r in rs], 0.95), 1) for d in range(len(DAYS))],
            "fri_closes": [round(x, 1) for x in fri],
        }
        kinds = rs[0]["flows"].keys()
        out["flows_pct_volume"] = {k: [statistics.mean(r["flows"][k][d] / (r["vols"][d] or 1) for r in rs)
                                       for d in range(len(DAYS))] for k in kinds}
        out["returns"] = {k: {"median": statistics.median(r["rets"][k] for r in rs),
                              "p05": _pct([r["rets"][k] for r in rs], 0.05),
                              "p95": _pct([r["rets"][k] for r in rs], 0.95)} for k in kinds}
        return out

    def bands(rs):
        n = len(rs[0]["bars"])
        return {str(q): [round(_pct([r["bars"][i] for r in rs], q), 1) for i in range(n)] for q in (0.05, 0.25, 0.5, 0.75, 0.95)}

    allruns = [r for rs in results.values() for r in rs]
    out = {
        "meta": {
            "friday_close": FRI, "thursday_low": mon.THURSDAY_LOW, "ma200": round(mon.MA200, 2),
            "ma200_slope": MA200_SLOPE, "gamma_flip": GAMMA_FLIP, "vix": mon.VIX, "days": DAYS,
            "bars_per_day": DAY // 5, "runs": len(allruns),
            "factors": {
                "cpi": {k: {kk: v[kk] for kk in ("label", "p", "detail")} for k, v in CPI.items()},
                "crwv": {k: {kk: v[kk] for kk in ("label", "p", "detail")} for k, v in CRWV.items()},
                "forced": {k: {kk: v[kk] for kk in ("label", "p", "detail")} for k, v in FORCED.items()},
            },
            "population": {k: {"label": AGENT_TYPES[k].label, "does": AGENT_TYPES[k].description,
                               "who": mon.WHO.get(k, "Systematic trend-following funds (CTAs) on long lookbacks")}
                           for k in list(mon.POPULATION) + ["cta_trend"]},
        },
        "all": {**stats(allruns), "bands": bands(allruns)},
        "paths": {},
        "factor_effects": {},
    }
    for k, rs in results.items():
        c, w, f = k.split("|")
        st = stats(rs)
        med = st["fri_close"]["0.5"]
        rep = min(rs, key=lambda r: abs(r["closes"][-1] - med))
        out["paths"][k] = {
            "cpi": c, "crwv": w, "forced": f, "p": prob[k], "stats": st, "bands": bands(rs),
            "replay": {kk: rep[kk] for kk in ("seed", "bars", "fair", "bar_flows", "bar_vol", "events", "closes")},
        }
    # factor effects: median Friday close in each level of a factor, pooled over the others (probability-weighted by allocation)
    for fac, idx, table in (("cpi", 0, CPI), ("crwv", 1, CRWV), ("forced", 2, FORCED)):
        out["factor_effects"][fac] = {lvl: round(statistics.median(r["closes"][-1] for k, rs in results.items()
                                                                  if k.split("|")[idx] == lvl for r in rs), 1)
                                      for lvl in table}
    dest = ROOT / "analyses" / "output" / "week_nov9.json"
    dest.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {dest} ({dest.stat().st_size // 1024} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
