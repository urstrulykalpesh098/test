"""Command line: python -m marketsim {run,list,validate,traders}"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from .agents import AGENT_TYPES
from .analysis import market_stats, monte_carlo_summary, trader_stats
from .engine import run_scenario
from .forecast import TIMESFM_LICENSE_NOTE, load_series, make_forecast, write_forecast_csv
from .report import write_outputs
from .scenario import Scenario, attach_forecast

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


def _note_source(fc) -> None:
    if fc.source == "timesfm-3":
        print(f"  baseline forecast: TimesFM-3 (local). {TIMESFM_LICENSE_NOTE}", file=sys.stderr)
    else:
        print("  baseline forecast: statistical random walk "
              "(TimesFM not installed; see requirements-timesfm.txt)", file=sys.stderr)


def prepare_forecast(sc: Scenario, args) -> None:
    """Attach a baseline forecast from --forecast-csv or the scenario's baseline_forecast."""
    cfg = dict(sc.baseline_forecast or {})
    if args.forecast_csv:
        cfg["csv"] = args.forecast_csv
    if not cfg.get("csv"):
        return
    csv_path = Path(args.forecast_csv) if args.forecast_csv else sc.resolve_path(cfg["csv"])
    column = args.column or cfg.get("column")
    model = args.model or cfg.get("model", "auto")
    tps = args.ticks_per_step or int(cfg.get("ticks_per_step", 10))
    history = load_series(csv_path, column)
    horizon = math.ceil(sc.ticks / tps)
    fc = make_forecast(history, horizon, model, cfg.get("checkpoint"))
    _note_source(fc)
    attach_forecast(sc, fc, tps, bool(cfg.get("vol_from_band", True)))


def cmd_forecast(args) -> None:
    history = load_series(args.csv, args.column)
    fc = make_forecast(history, args.horizon, args.model or "auto")
    _note_source(fc)
    lo, hi = fc.band()
    print(f"last value {fc.last:,.2f}; {fc.horizon}-step forecast ({fc.source}):")
    for h in sorted({1, 5, 10, 20, fc.horizon} & set(range(1, fc.horizon + 1))):
        band = f"   10-90%: {lo[h - 1]:,.2f} .. {hi[h - 1]:,.2f}" if lo and hi else ""
        print(f"  step {h:>4}: median {fc.median[h - 1]:,.2f} ({fc.median[h - 1] / fc.last - 1:+.1%}){band}")
    if args.out:
        write_forecast_csv(fc, Path(args.out))
        print(f"  written: {args.out}")


def cmd_run(args) -> None:
    path = resolve(args.scenario)
    sc = Scenario.load(path)
    if args.ticks:
        sc.ticks = args.ticks
        sc.events = [e for e in sc.events if e.tick < sc.ticks]
    prepare_forecast(sc, args)
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
    p.add_argument("--forecast-csv", help="price history CSV; fair value follows its baseline forecast")
    p.add_argument("--column", help="CSV column to use (default: close/price/value)")
    p.add_argument("--model", choices=("auto", "timesfm", "statistical"), help="forecast backend (default auto)")
    p.add_argument("--ticks-per-step", type=int, help="simulation ticks per CSV row (default 10)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("forecast", help="baseline forecast of a price history CSV (TimesFM-3 if installed)")
    p.add_argument("csv")
    p.add_argument("--column")
    p.add_argument("--horizon", type=int, default=30)
    p.add_argument("--model", choices=("auto", "timesfm", "statistical"))
    p.add_argument("--out", help="write forecast quantiles to this CSV")
    p.set_defaults(func=cmd_forecast)

    sub.add_parser("list", help="list bundled scenarios").set_defaults(func=cmd_list)
    sub.add_parser("traders", help="describe trader types and their parameters").set_defaults(func=cmd_traders)
    p = sub.add_parser("validate", help="check scenario files for mistakes")
    p.add_argument("scenarios", nargs="+")
    p.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    if getattr(args, "runs", 1) < 1:
        parser.error("--runs must be >= 1")
    if (getattr(args, "ticks_per_step", None) or 1) < 1 or getattr(args, "horizon", 1) < 1:
        parser.error("--ticks-per-step and --horizon must be >= 1")
    try:
        args.func(args)
    except (ValueError, RuntimeError, OSError) as exc:
        raise SystemExit(f"error: {exc}")


if __name__ == "__main__":
    main()
