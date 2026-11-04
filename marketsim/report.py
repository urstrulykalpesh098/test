"""Self-contained HTML report (inline SVG, no external assets) plus CSV/JSON exports."""
from __future__ import annotations

import csv
import html
import json
import math
from pathlib import Path
from typing import List, Optional, Sequence

from .analysis import _pct, event_impacts, market_stats, monte_carlo_summary, trader_stats
from .engine import RunResult

W, H, PAD_L, PAD_R, PAD_T, PAD_B = 880, 260, 56, 16, 16, 28


def _fmt_pct(x: float, digits: int = 1) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:+.{digits}f}%"


def _fmt_num(x: float, digits: int = 2) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{digits}f}"


def _scale(lo: float, hi: float, n: int):
    if hi - lo < 1e-12:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.06
    lo, hi = (max(0.0, lo - pad) if lo >= 0 else lo - pad), hi + pad
    x = lambda i: PAD_L + (W - PAD_L - PAD_R) * (i / max(1, n - 1))
    y = lambda v: PAD_T + (H - PAD_T - PAD_B) * (1 - (v - lo) / (hi - lo))
    return x, y, lo, hi


def _axes(x, y, lo, hi, n, fmt) -> str:
    parts = []
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        yy = y(v)
        parts.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="tick" x="{PAD_L - 6}" y="{yy + 4:.1f}" text-anchor="end">{fmt(v)}</text>')
    for k in range(6):
        i = round((n - 1) * k / 5)
        parts.append(f'<text class="tick" x="{x(i):.1f}" y="{H - 8}" text-anchor="middle">{i}</text>')
    return "".join(parts)


def _path(values: Sequence[Optional[float]], x, y) -> str:
    d, pen = [], False
    for i, v in enumerate(values):
        if v is None:
            pen = False
            continue
        d.append(f"{'L' if pen else 'M'}{x(i):.1f},{y(v):.1f}")
        pen = True
    return " ".join(d)


def _event_marks(events, x) -> str:
    out = []
    for ev in events:
        xx = x(ev["tick"])
        out.append(
            f'<g class="event"><line x1="{xx:.1f}" x2="{xx:.1f}" y1="{PAD_T}" y2="{H - PAD_B}"/>'
            f'<title>t={ev["tick"]}: {html.escape(ev["headline"])}</title></g>'
        )
    return "".join(out)


def line_chart(series: List[tuple], events=(), fmt=lambda v: f"{v:.2f}", band=None) -> str:
    """series: [(label, values, css_class)]; band: (lower, upper) shaded area."""
    n = max(len(v) for _, v, _ in series)
    vals = [v for _, vs, _ in series for v in vs if v is not None]
    if band:
        vals += list(band[0]) + list(band[1])
    x, y, lo, hi = _scale(min(vals), max(vals), n)
    body = [_axes(x, y, lo, hi, n, fmt)]
    if band:
        lower, upper = band
        pts = [f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(upper)]
        pts += [f"{x(i):.1f},{y(v):.1f}" for i, v in reversed(list(enumerate(lower)))]
        body.append(f'<polygon class="band" points="{" ".join(pts)}"/>')
    body.append(_event_marks(events, x))
    for label, values, cls in series:
        body.append(f'<path class="line {cls}" d="{_path(values, x, y)}"><title>{html.escape(label)}</title></path>')
    legend = "".join(f'<span class="key {cls}">{html.escape(label)}</span>' for label, _, cls in series)
    return f'<div class="legend">{legend}</div><svg viewBox="0 0 {W} {H}" role="img">{"".join(body)}</svg>'


def bar_chart(values: Sequence[float], events=(), fmt=lambda v: f"{v:,.0f}") -> str:
    n = len(values)
    x, y, lo, hi = _scale(0, max(values) or 1, n)
    base = y(0)
    bw = max(0.6, (W - PAD_L - PAD_R) / n * 0.8)
    bars = "".join(
        f'<rect class="bar" x="{x(i) - bw / 2:.1f}" y="{y(v):.1f}" width="{bw:.1f}" height="{max(0, base - y(v)):.1f}"/>'
        for i, v in enumerate(values) if v
    )
    return f'<svg viewBox="0 0 {W} {H}" role="img">{_axes(x, y, lo, hi, n, fmt)}{_event_marks(events, x)}{bars}</svg>'


def histogram(values: List[float], bins: int = 24) -> str:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        hi = lo + 1e-6
    counts = [0] * bins
    for v in values:
        counts[min(bins - 1, int((v - lo) / (hi - lo) * bins))] += 1
    top = max(counts)
    inner_w = W - PAD_L - PAD_R
    bw = inner_w / bins
    rects = []
    for i, c in enumerate(counts):
        h = (H - PAD_T - PAD_B) * c / top
        x0 = lo + (hi - lo) * i / bins
        rects.append(
            f'<rect class="bar {"neg" if x0 + (hi - lo) / bins <= 0 else ""}" x="{PAD_L + i * bw + 1:.1f}" '
            f'y="{H - PAD_B - h:.1f}" width="{bw - 2:.1f}" height="{h:.1f}"><title>{_fmt_pct(x0)} … '
            f'{_fmt_pct(x0 + (hi - lo) / bins)}: {c} runs</title></rect>'
        )
    ticks = "".join(
        f'<text class="tick" x="{PAD_L + inner_w * k / 4:.1f}" y="{H - 8}" text-anchor="middle">'
        f'{_fmt_pct(lo + (hi - lo) * k / 4, 0)}</text>' for k in range(5)
    )
    return f'<svg viewBox="0 0 {W} {H}" role="img">{"".join(rects)}{ticks}</svg>'


def _table(headers: List[str], rows: List[List[str]], num_from: int = 1) -> str:
    head = "".join(f"<th{' class=num' if i >= num_from else ''}>{h}</th>" for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f"<td{' class=num' if i >= num_from else ''}>{c}</td>" for i, c in enumerate(r)) + "</tr>"
        for r in rows
    )
    return f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1b;--muted:#6b6b66;--line:#e4e3de;
--price:#2457c5;--fund:#d0731c;--band:rgba(36,87,197,.14);--bar:#8e9bb5;--neg:#c2413b;--event:#c2413b;--pos:#2f8a4c}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#151514;--card:#1f1f1d;--fg:#ecebe6;--muted:#a3a29b;
--line:#34332f;--price:#7aa2ff;--fund:#f0a050;--band:rgba(122,162,255,.18);--bar:#6c7894;--neg:#ef6b63;--event:#ef6b63;--pos:#5fc27f}}
:root[data-theme=dark]{--bg:#151514;--card:#1f1f1d;--fg:#ecebe6;--muted:#a3a29b;--line:#34332f;--price:#7aa2ff;--fund:#f0a050;
--band:rgba(122,162,255,.18);--bar:#6c7894;--neg:#ef6b63;--event:#ef6b63;--pos:#5fc27f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 10px}
.sub{color:var(--muted);margin:0 0 20px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.kpi b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.kpi span{color:var(--muted);font-size:13px}
svg{width:100%;height:auto;display:block}.grid{stroke:var(--line)}.tick{fill:var(--muted);font-size:11px}
.line{fill:none;stroke-width:1.6}.price{stroke:var(--price)}.fund{stroke:var(--fund);stroke-dasharray:4 3}.median{stroke:var(--price)}
.band{fill:var(--band)}.bar{fill:var(--bar)}.bar.neg{fill:var(--neg)}.event line{stroke:var(--event);stroke-dasharray:3 3;stroke-width:1.2}
.legend{display:flex;gap:16px;font-size:13px;color:var(--muted);margin-bottom:4px}.key:before{content:"";display:inline-block;width:14px;height:3px;margin-right:6px;vertical-align:middle;background:var(--price)}
.key.fund:before{background:var(--fund)}.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{color:var(--muted);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}.pos{color:var(--pos)}.negt{color:var(--neg)}
.note{color:var(--muted);font-size:13px}
"""


def _signed(x: float) -> str:
    cls = "pos" if x > 0 else "negt" if x < 0 else ""
    return f'<span class="{cls}">{_fmt_pct(x)}</span>'


def forecast_overlay(run: RunResult) -> dict:
    """Baseline forecast mapped onto simulation ticks, in price units."""
    sc = run.scenario
    fc, tps, f0 = sc.forecast, sc.ticks_per_step, sc.initial_fundamental
    scale = lambda vals: [f0 * r for r in fc.relative_path(sc.ticks, tps, vals)]
    lo, hi = fc.band()
    return {
        "median": scale(fc.median),
        "low": scale(lo) if lo else None,
        "high": scale(hi) if hi else None,
    }


def _forecast_section(runs: List[RunResult]) -> str:
    run = runs[0]
    sc = run.scenario
    fc = sc.forecast
    ov = forecast_overlay(run)
    n = sc.ticks
    if len(runs) > 1:
        sim = [_pct([r.series["price"][i] for r in runs], 0.5) for i in range(n)]
        sim_label = "Simulated price (median of runs)"
    else:
        sim, sim_label = run.series["price"], "Simulated price"
    source = "TimesFM-3" if fc.source == "timesfm-3" else "Statistical baseline (random walk; TimesFM not installed)"
    band = (ov["low"], ov["high"]) if ov["low"] and ov["high"] else None
    end_gap = sim[-1] / ov["median"][-1] - 1
    gaps = [p / m - 1 for p, m in zip(sim, ov["median"])]
    worst = max(gaps, key=abs)
    outside = sum(1 for p, lo, hi in zip(sim, *band) if p < lo or p > hi) if band else 0
    kpis = [
        ("Baseline forecast end", _fmt_num(ov["median"][-1]), f'{_fmt_pct(ov["median"][-1] / sc.initial_fundamental - 1)} over the horizon'),
        ("Scenario vs baseline (end)", _fmt_pct(end_gap), "simulated price vs forecast median"),
        ("Largest gap from baseline", _fmt_pct(worst), "at any tick"),
        ("Ticks outside 10–90% band", f"{outside / n * 100:.0f}%" if band else "–", "how unusual the scenario path is"),
    ]
    note = (f"Source: {html.escape(source)}. Fitted on {len(fc.history)} historical points (last value "
            f"{fc.last:,.2f}, shown indexed to {sc.initial_fundamental:,.2f}); "
            f"{fc.horizon} forecast steps × {sc.ticks_per_step} ticks per step. Fair value follows the forecast "
            "median and scenario events push it away from there. ")
    if fc.source == "timesfm-3":
        note += "TimesFM-3 weights are licensed by Google for non-commercial, non-production use only."
    return ("<h2>Scenario vs baseline forecast</h2><div class=\"card\">" + line_chart(
        [(sim_label, sim, "price"), ("Baseline forecast median", ov["median"], "fund")],
        run.events, band=band) + f'<p class="note">{note} Shaded band: forecast 10th–90th percentile.</p></div>'
        + '<div class="kpis">' + "".join(
            f'<div class="kpi"><span>{a}</span><b>{b}</b><span>{c}</span></div>' for a, b, c in kpis) + "</div>")


def render_html(runs: List[RunResult]) -> str:
    run = runs[0]
    sc = run.scenario
    ms = market_stats(run)
    ev = run.events
    s = run.series

    kpis = [
        ("Final price", _fmt_num(ms["final_price"]), f'{_fmt_pct(ms["total_return"])} vs start'),
        ("Fair value", _fmt_num(ms["final_fundamental"]), f'{_fmt_pct(ms["fundamental_return"])} vs start'),
        ("Max drawdown", _fmt_pct(ms["max_drawdown"]), f'low {_fmt_num(ms["min_price"])}'),
        ("Worst mispricing", _fmt_pct(ms["max_abs_mispricing"]), f'avg {_fmt_pct(ms["mean_abs_mispricing"])}'),
        ("Avg spread", f'{_fmt_num(ms["avg_spread_bps"], 1)} bps', f'max {_fmt_num(ms["max_spread_bps"], 0)} bps'),
        ("Volume", f'{ms["total_volume"]:,}', f'{ms["total_trades"]:,} trades'),
    ]
    kpi_html = "".join(f'<div class="kpi"><span>{a}</span><b>{b}</b><span>{c}</span></div>' for a, b, c in kpis)

    parts = [f"<h1>{html.escape(sc.name.replace('_', ' ').title())}</h1>",
             f'<p class="sub">{html.escape(sc.description)}<br>{sc.ticks} ticks · '
             f'{sum(p.count for p in sc.population)} traders · seed {run.seed}'
             f'{f" · {len(runs)} Monte Carlo runs" if len(runs) > 1 else ""}</p>',
             f'<div class="kpis">{kpi_html}</div>']

    if sc.forecast is not None:
        parts.append(_forecast_section(runs))

    if len(runs) > 1:
        mc = monte_carlo_summary(runs)
        n = sc.ticks
        lows = [_pct([r.series["price"][i] for r in runs], 0.05) for i in range(n)]
        highs = [_pct([r.series["price"][i] for r in runs], 0.95) for i in range(n)]
        med = [_pct([r.series["price"][i] for r in runs], 0.5) for i in range(n)]
        fund_med = [_pct([r.series["fundamental"][i] for r in runs], 0.5) for i in range(n)]
        parts.append("<h2>Range of outcomes</h2>")
        parts.append('<div class="card">' + line_chart(
            [("Median price", med, "median"), ("Median fair value", fund_med, "fund")], ev, band=(lows, highs)
        ) + '<p class="note">Shaded band: 5th–95th percentile of price across all runs. Dashed red lines: scheduled events (hover for headline).</p></div>')
        parts.append('<div class="kpis">' + "".join(
            f'<div class="kpi"><span>{a}</span><b>{b}</b><span>{c}</span></div>' for a, b, c in [
                ("Chance of loss", f'{mc["prob_loss"] * 100:.0f}%', "price ends below start"),
                ("Chance of ≥10% drawdown", f'{mc["prob_drawdown_10"] * 100:.0f}%', "at any point in the run"),
                ("Median return", _fmt_pct(mc["total_return"][0.5]), f'5–95%: {_fmt_pct(mc["total_return"][0.05])} … {_fmt_pct(mc["total_return"][0.95])}'),
                ("Median max drawdown", _fmt_pct(mc["max_drawdown"][0.5]), f'worst 5%: {_fmt_pct(mc["max_drawdown"][0.05])}'),
            ]) + "</div>")
        parts.append('<div class="card"><b>Distribution of final returns</b>' + histogram(mc["final_returns"]) + "</div>")
        parts.append("<h2>Trader returns across runs</h2>" + _table(
            ["Trader type", "5th pct", "Median", "95th pct"],
            [[next(r["label"] for r in trader_stats(run) if r["kind"] == k),
              _signed(v[0.05]), _signed(v[0.5]), _signed(v[0.95])] for k, v in mc["trader_returns"].items()]))
        parts.append(f"<h2>Example run (seed {run.seed})</h2>")
    else:
        parts.append("<h2>Price vs fair value</h2>")

    parts.append('<div class="card">' + line_chart(
        [("Price", s["price"], "price"), ("Fair value", s["fundamental"], "fund")], ev) + "</div>")
    parts.append('<div class="card"><b>Volume per tick</b>' + bar_chart(s["volume"], ev) + "</div>")
    parts.append('<div class="card"><b>Bid–ask spread (bps)</b>' + line_chart(
        [("Spread", s["spread_bps"], "price")], ev, fmt=lambda v: f"{v:.0f}") + "</div>")
    parts.append('<div class="card"><b>Market sentiment</b>' + line_chart(
        [("Sentiment", s["sentiment"], "price")], ev, fmt=lambda v: f"{v:+.1f}") + "</div>")

    if ev:
        imp = event_impacts(run)
        parts.append("<h2>Event impact</h2>" + _table(
            ["Tick", "Headline", "Fair-value move", "+10 ticks", "+50 ticks", "+200 ticks", "Worst", "Overshoot vs value"],
            [[str(r["tick"]), html.escape(r["headline"]), _signed(r["fair_value_change"]),
              _signed(r.get("return_10", float("nan"))), _signed(r.get("return_50", float("nan"))),
              _signed(r.get("return_200", float("nan"))), _signed(r["worst_return"]), _signed(r["overshoot"])]
             for r in imp], num_from=2))

    ts = trader_stats(run)
    parts.append("<h2>Who made and lost money</h2>" + _table(
        ["Trader type", "Agents", "Total P&L", "Return", "vs buy &amp; hold", "% losing", "Avg shares at end", "Volume", "Panic sells"],
        [[r["label"], str(r["count"]), _fmt_num(r["pnl"], 0), _signed(r["return"]), _signed(r["vs_buy_and_hold"]),
          f'{r["pct_losing"] * 100:.0f}%', _fmt_num(r["avg_final_shares"], 0), f'{r["volume"]:,}', str(r["panics"])]
         for r in ts]))
    parts.append('<p class="note">Generated locally by marketsim. Synthetic agent-based simulation for exploring '
                 'scenarios; not investment advice and not a price forecast.</p>')

    title = html.escape(sc.name.replace("_", " ").title()) + " Simulation"
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>'
            f"<style>{CSS}</style></head><body><main>{''.join(parts)}</main></body></html>")


def write_outputs(runs: List[RunResult], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    run = runs[0]
    (out_dir / "report.html").write_text(render_html(runs), encoding="utf-8")

    with open(out_dir / "timeseries.csv", "w", newline="", encoding="utf-8") as fh:
        keys = list(run.series)
        w = csv.writer(fh)
        w.writerow(["tick"] + keys)
        for i in range(len(run.series["price"])):
            w.writerow([i] + [run.series[k][i] for k in keys])

    summary = {
        "scenario": run.scenario.name,
        "seed": run.seed,
        "market": market_stats(run),
        "events": event_impacts(run),
        "traders": trader_stats(run),
    }
    if run.scenario.forecast is not None:
        fc = run.scenario.forecast
        summary["baseline_forecast"] = {
            "source": fc.source,
            "history_points": len(fc.history),
            "horizon_steps": fc.horizon,
            "ticks_per_step": run.scenario.ticks_per_step,
            "median": fc.median,
            "quantiles": {str(q): v for q, v in fc.quantiles.items()},
        }
    if len(runs) > 1:
        mc = monte_carlo_summary(runs)
        mc.pop("final_returns")
        summary["monte_carlo"] = json.loads(json.dumps(mc, default=str))
        summary["seeds"] = [r.seed for r in runs]
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary
