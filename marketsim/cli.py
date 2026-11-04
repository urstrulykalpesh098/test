"""Command line: python -m marketsim {run,list,validate,traders}"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agents import AGENT_TYPES
from .analysis import market_stats, monte_carlo_summary, trader_stats
from .engine import run_scenario
from .report import write_outputs
from .scenario import Scenario

ROOT = Path(__file__).resolve().parent.parent
SCENARIO_DIR = ROOT / "scenarios"


def resolve(name: str) -> Path:
    path = Path(name)
    if path.exists():
        return path
    candidate = SCENARIO_DIR / f"{name}.json"
    if candidate.exists():
        return candidate
    raise SystemExit(f"scenario not found: {name} (try `python -m marketsim list`)")


def cmd_list(_args) -> None:
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        sc = Scenario.load(path)
        print(f"{path.stem:<22} {sc.description}")


def cmd_traders(_args) -> None:
    for kind, cls in AGENT_TYPES.items():
        print(f"{kind:<16} {cls.label}: {cls.description}")
        params = {**cls.BASE, **cls.DEFAULTS}
        print("    " + ", ".join(f"{k}={v}" for k, v in params.items()))


def cmd_validate(args) -> None:
    for name in args.scenarios:
        Scenario.load(resolve(name))
        print(f"ok  {name}")


def cmd_run(args) -> None:
    path = resolve(args.scenario)
    sc = Scenario.load(path)
    if args.ticks:
        sc.ticks = args.ticks
        sc.events = [e for e in sc.events if e.tick < sc.ticks]
    seeds = list(range(args.seed, args.seed + args.runs))
    runs = []
    for i, seed in enumerate(seeds, 1):
        runs.append(run_scenario(sc, seed))
        if len(seeds) > 1:
            print(f"\r  run {i}/{len(seeds)}", end="", file=sys.stderr, flush=True)
    if len(seeds) > 1:
        print(file=sys.stderr)

    out = Path(args.out) if args.out else ROOT / "reports" / (
        f"{sc.name}-seed{args.seed}" + (f"-x{args.runs}" if args.runs > 1 else ""))
    write_outputs(runs, out)

    ms = market_stats(runs[0])
    print(f"\n{sc.name}  (seed {args.seed}, {sc.ticks} ticks)")
    print(f"  price {ms['initial_price']:.2f} -> {ms['final_price']:.2f} ({ms['total_return']:+.1%}); "
          f"fair value -> {ms['final_fundamental']:.2f} ({ms['fundamental_return']:+.1%})")
    print(f"  max drawdown {ms['max_drawdown']:.1%}, worst mispricing {ms['max_abs_mispricing']:.1%}, "
          f"avg spread {ms['avg_spread_bps']:.1f} bps")
    print("  trader returns:")
    for r in trader_stats(runs[0]):
        print(f"    {r['label']:<18} {r['return']:+7.2%}   ({r['pct_losing']:.0%} of agents lost money)")
    if len(runs) > 1:
        mc = monte_carlo_summary(runs)
        tr = mc["total_return"]
        print(f"  across {len(runs)} runs: median return {tr[0.5]:+.1%} "
              f"(5-95%: {tr[0.05]:+.1%} .. {tr[0.95]:+.1%}), P(loss) {mc['prob_loss']:.0%}, "
              f"P(drawdown>=10%) {mc['prob_drawdown_10']:.0%}")
    print(f"\n  report: {out / 'report.html'}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="marketsim", description="Agent-based market simulator with trader archetypes.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="run a scenario and write a report")
    p.add_argument("scenario", help="scenario name (see `list`) or path to a JSON file")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--runs", type=int, default=1, help="Monte Carlo runs with consecutive seeds")
    p.add_argument("--ticks", type=int, help="override scenario length")
    p.add_argument("--out", help="output directory (default reports/<scenario>-seed<N>)")
    p.set_defaults(func=cmd_run)

    sub.add_parser("list", help="list bundled scenarios").set_defaults(func=cmd_list)
    sub.add_parser("traders", help="describe trader types and their parameters").set_defaults(func=cmd_traders)
    p = sub.add_parser("validate", help="check scenario files for mistakes")
    p.add_argument("scenarios", nargs="+")
    p.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    if getattr(args, "runs", 1) < 1:
        parser.error("--runs must be >= 1")
    try:
        args.func(args)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}")


if __name__ == "__main__":
    main()
