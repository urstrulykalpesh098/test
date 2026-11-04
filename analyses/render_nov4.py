"""Render analyses/output/nov4_2026.json into a self-contained HTML report."""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from marketsim.report import CSS, line_chart  # noqa: E402

TPD = 10
OUT = ROOT / "analyses" / "output"


def pct(x, d=1):
    return f"{x * 100:+.{d}f}%"


def sig(x, d=1):
    cls = "pos" if x > 0.0005 else "negt" if x < -0.0005 else ""
    return f'<span class="{cls}">{pct(x, d)}</span>'


def daily(values):
    """End-of-day samples so the x-axis reads in trading days."""
    return [values[0]] + [values[i] for i in range(TPD - 1, len(values), TPD)]


def table(headers, rows, num_from=1):
    th = "".join(f"<th{' class=num' if i >= num_from else ''}>{h}</th>" for i, h in enumerate(headers))
    tb = "".join("<tr>" + "".join(f"<td{' class=num' if i >= num_from else ''}>{c}</td>"
                                  for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="tablewrap"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>'


def rng(s):
    return f'{sig(s["median"])} <span class="muted">({pct(s["p05"])} … {pct(s["p95"])})</span>'


def ev_marks(tick, headline):
    return [{"tick": tick // TPD, "headline": headline}]


EXTRA_CSS = """
.muted{color:var(--muted);font-size:13px}.lead{font-size:17px;margin:6px 0 18px}
.bottom{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--price);border-radius:10px;padding:12px 16px}
.bottom li{margin:6px 0}.take{border-left:4px solid var(--fund);padding:6px 12px;margin:12px 0;background:var(--card);border-radius:6px}
.key.median:before{background:var(--price)}h3{font-size:15px;margin:18px 0 6px}
.src a{color:var(--muted)}ol,ul{padding-left:20px}
"""


def render(d):
    E, F, G = d["election"], d["fed"], d["energy"]
    parts = []
    parts.append("<h1>Market What-Ifs: 4 Nov 2026</h1>")
    parts.append(f'<p class="sub">Agent-based simulations (marketsim) of three live situations · '
                 f'{d["runs_per_variant"]} runs per variant · 229 simulated traders · prices indexed to 100</p>')

    er, em = E["real"]["returns"], E["mood"]["returns"]
    b = F["blended_5d"]
    gs, gn = G["stressed"], G["normal"]
    parts.append('<div class="bottom"><b>Bottom line</b><ul>'
                 f'<li><b>Election rally:</b> how the rally behaves after the first week tells you what kind it is. '
                 f'If it reflects a real reassessment of value, the model keeps roughly half of it after a month '
                 f'(median {pct(er["20"]["median"])}). If it is only mood, the gain is gone within a month '
                 f'(median {pct(em["20"]["median"])}, below the starting price in {em["20"]["prob_down"]:.0%} of runs).</li>'
                 f'<li><b>Fed, 9 Dec:</b> the most likely outcome barely moves the market '
                 f'(5-day median {pct(F["hike_25bp_as_expected"]["returns"]["5"]["median"])}). The risk is a surprise 50bp hike. '
                 f'Weighting all three outcomes by their odds gives a median of {pct(b["median"])}, '
                 f'a {b["prob_down_2pct"]:.0%} chance of a drop of more than 2%, and a 1-in-20 worst case of {pct(b["p05"])}.</li>'
                 f'<li><b>Energy:</b> liquidity, not the news itself, decides the damage. If market makers pull back, '
                 f'the first-day drop goes from {pct(gn["returns"]["1"]["median"])} to {pct(gs["returns"]["1"]["median"])}, '
                 f'the bid–ask spread goes from {gn["spread_bps_first_5d"]:.0f} to {gs["spread_bps_first_5d"]:.0f} bps, '
                 f'and the 1-in-20 worst drop deepens to {pct(gs["worst_10d"]["p05"])}.</li>'
                 "</ul></div>")

    parts.append("<h2>What is happening today</h2><ul>"
                 "<li>Democrats won control of Congress in the 3 Nov midterms. The S&amp;P 500 rose about 1.5% "
                 "intraday and the Dow 2.4–2.9%, its best session in months.</li>"
                 "<li>Oil extended its slide, as the result was read as opposition to the Iran war. "
                 "Big tech stocks bounced about 3% after a selloff.</li>"
                 "<li>The Fed held at 3.75–4.00% on 28 Oct, with two officials voting for a hike. "
                 "Markets price about a 77% chance of a 25bp hike on 9 Dec.</li></ul>"
                 '<p class="muted">Intraday figures differ between sources. Event sizes below are rounded from these reports.</p>')

    # ---------------- Study 1
    parts.append("<h2>1 · Will the election rally last?</h2>")
    parts.append("<p>Two versions of the same headline. <b>Value re-rated:</b> the result really "
                 "changes what companies are worth (+1.5%). <b>Mood only:</b> traders feel better, but "
                 "nothing fundamental changed. Both start from the same mood boost.</p>")
    r, m = E["real"]["bands"], E["mood"]["bands"]
    parts.append('<div class="card">' + line_chart(
        [("Value re-rated: median price", daily(r["p50"]), "price"),
         ("Mood only: median price", daily(m["p50"]), "fund")],
        ev_marks(10, E["real"]["events"][0]["headline"]), band=(daily(m["p05"]), daily(m["p95"]))) +
        '<p class="note">X-axis: trading days. Shaded: 5th–95th percentile of the mood-only case.</p></div>')
    parts.append(table(
        ["Version", "After 1 day", "After 5 days", "After 20 days", "Chance below start at 20 days"],
        [[E[k]["label"], rng(E[k]["returns"]["1"]), rng(E[k]["returns"]["5"]), rng(E[k]["returns"]["20"]),
          f'{E[k]["returns"]["20"]["prob_down"]:.0%}'] for k in ("real", "mood")]))
    parts.append('<div class="take"><b>Takeaway.</b> In both versions, trend followers and retail traders push '
                 'prices higher during the first week. After that, the paths split. A rally driven only by mood is '
                 'fully given back within a month, while a real re-rating keeps part of the gain. '
                 '<b>What to watch:</b> whether the index holds its gains through next week. In the model, giving '
                 'back the first-day gain within 5 days points to mood rather than value.</div>')

    # ---------------- Study 2
    parts.append("<h2>2 · Fed decision on 9 Dec</h2>")
    parts.append("<p>The decision lands about 24 trading days from now. There are three possible outcomes, "
                 "weighted by market odds plus a small chance of a 50bp hike, which is my assumption.</p>")
    keys = ("hike_25bp_as_expected", "surprise_hold", "surprise_hike_50bp")
    t0 = F["event_tick"]
    lo = lambda b: daily(b["p50"])[t0 // TPD - 3:]
    parts.append('<div class="card">' + line_chart(
        [("25bp hike as priced", lo(F[keys[0]]["bands"]), "price"),
         ("Surprise hold", lo(F[keys[1]]["bands"]), "fund"),
         ("Surprise 50bp hike", lo(F[keys[2]]["bands"]), "negline")],
        [{"tick": 3, "headline": "9 Dec FOMC decision"}]) +
        '<p class="note">Median price from 3 days before the decision. X-axis: trading days.</p></div>')
    parts.append(table(
        ["Outcome", "Odds used", "1 day", "5 days", "15 days", "Worst dip in 15 days (median / 1-in-20)"],
        [[F[k]["label"], f'{F[k]["probability"]:.0%}', rng(F[k]["returns"]["1"]), rng(F[k]["returns"]["5"]),
          rng(F[k]["returns"]["15"]), f'{sig(F[k]["worst_15d"]["median"])} / {sig(F[k]["worst_15d"]["p05"])}']
         for k in keys]))
    parts.append(f'<div class="take"><b>Takeaway.</b> A hike as expected is close to a non-event. The skew comes '
                 f'from surprises. A 50bp hike causes a median 5-day drop of '
                 f'{pct(F[keys[2]]["returns"]["5"]["median"])}, larger than the 4.5% hit to value, because trend '
                 f'followers and retail traders keep selling after the news. A surprise hold gives '
                 f'{pct(F[keys[1]]["returns"]["5"]["median"])}. Weighted by the odds, the 5-day picture is a median of '
                 f'{pct(b["median"])}, a range of {pct(b["p05"])} to {pct(b["p95"])}, and a {b["prob_down_2pct"]:.0%} '
                 f'chance of losing more than 2%. <b>What to watch:</b> the hike odds and anything Fed officials '
                 f'say about a 50bp move. That tail is where most of the downside is.</div>')

    # ---------------- Study 3
    parts.append("<h2>3 · Energy stocks while oil slides</h2>")
    parts.append("<p>A typical energy stock has its value cut 5% on lower oil, mood turns negative and volatility "
                 "is higher (1.5%/day). It is run twice: once with normal liquidity, and once where market makers "
                 "step back for 5 days (stress 0.6), as dealers often do in fast-moving commodity markets.</p>")
    n_, s_ = G["normal"]["bands"], G["stressed"]["bands"]
    parts.append('<div class="card">' + line_chart(
        [("Normal liquidity: median", daily(n_["p50"]), "price"),
         ("Stressed liquidity: median", daily(s_["p50"]), "negline"),
         ("Fair value (median)", daily(n_["fair_p50"]), "fund")],
        [{"tick": G["event_tick"] // TPD, "headline": "Oil slides; outlook cut"}],
        band=(daily(s_["p05"]), daily(s_["p95"]))) +
        '<p class="note">Shaded: 5th–95th percentile with stressed liquidity. X-axis: trading days.</p></div>')
    parts.append(table(
        ["Liquidity", "1 day", "5 days", "20 days", "Worst dip in 10 days (median / 1-in-20)",
         "Below fair value at the low (median / 1-in-20)", "Spread, first 5 days"],
        [[G[k]["label"], rng(G[k]["returns"]["1"]), rng(G[k]["returns"]["5"]), rng(G[k]["returns"]["20"]),
          f'{sig(G[k]["worst_10d"]["median"])} / {sig(G[k]["worst_10d"]["p05"])}',
          f'{sig(G[k]["overshoot_10d"]["median"])} / {sig(G[k]["overshoot_10d"]["p05"])}',
          f'{G[k]["spread_bps_first_5d"]:.0f} bps'] for k in ("normal", "stressed")]))
    parts.append('<div class="take"><b>Takeaway.</b> The value cut is the same 5% in both runs, but thin liquidity '
                 'brings the drop forward to day one, makes trading about 5× more expensive and makes the '
                 f'1-in-20 worst case much deeper ({pct(gn["worst_10d"]["p05"])} → {pct(gs["worst_10d"]["p05"])}). In the 1-in-20 case, price falls more than 20% below fair value before '
                 'value investors step in. <b>What to watch:</b> bid–ask spreads and order-book depth on energy '
                 'names, not just the oil price. Widening spreads are the early warning.</div>')

    # ---------------- Traders
    parts.append("<h2>Who wins and who loses</h2>")
    labels = list(E["real"]["traders"])
    parts.append(table(
        ["Trader type", "Election (re-rated)", "Election (mood)", "Energy (normal)", "Energy (stressed)"],
        [[l, sig(E["real"]["traders"][l]["median"], 2), sig(E["mood"]["traders"][l]["median"], 2),
          sig(G["normal"]["traders"][l]["median"], 2), sig(G["stressed"]["traders"][l]["median"], 2)]
         for l in labels]))
    parts.append('<p class="muted">Median return on each group\'s whole portfolio over the run. The pattern '
                 'is consistent: mean reverters lose in every case by betting against moves that are real; value '
                 'investors and institutions gain most when the news really changes value (the election re-rating); '
                 'retail traders lose most when liquidity is thin.</p>')

    # ---------------- Assumptions
    a = d["assumptions"]
    parts.append("<h2>Assumptions and limits</h2><ul>"
                 "<li><b>No real price history was used.</b> This environment's network rules block market-data "
                 "sites (FRED, Yahoo, Stooq), so prices are on a 100-point index and the TimesFM baseline was "
                 "skipped. To add it, allow a data host or provide CSVs and rerun.</li>"
                 f"<li>Fair-value volatility is {a['fair_value_daily_vol']:.1%}/day for the index and 1.5%/day for "
                 f"energy. Each trading day is {a['ticks_per_trading_day']} simulation steps.</li>"
                 f"<li>Fed outcome sizes: {html.escape(a['fed_outcome_sizes'])}. Odds: 75% / 20% / 5%. The "
                 "market prices the hike at 77%; the 5% for a 50bp hike is my assumption.</li>"
                 f"<li>Trader mix: {html.escape(a['trader_mix'])}.</li>"
                 "<li>This is a stylised model of <i>how</i> shocks spread through different kinds of traders. "
                 "It is not calibrated to the S&amp;P 500 or any stock, not a price forecast, and not "
                 "investment advice.</li></ul>")
    parts.append("<h2>Rerun it</h2><pre>python analyses/nov4_2026.py --runs 100\npython analyses/render_nov4.py</pre>")
    parts.append('<h2>Sources</h2><ul class="src">'
                 '<li><a href="https://www.thestreet.com/stock-market-today/stock-market-today-dow-jones-sp-500-nasdaq-updates-nov-04-2026">TheStreet: Stock Market Today, 4 Nov 2026</a></li>'
                 '<li><a href="https://finance.yahoo.com/markets/stocks/articles/stock-market-today-nov-4-145445827.html">Yahoo Finance: Dow rises 2.5% after Dems sweep midterms</a></li>'
                 '<li><a href="https://www.bloomberg.com/news/articles/2026-11-03/stock-market-today-dow-s-p-live-updates">Bloomberg: live updates, 4 Nov</a></li>'
                 '<li><a href="https://www.stocktitan.net/articles/stock-market-today-live-november-4-2026">StockTitan: stocks jump as Democrats win Congress</a></li>'
                 '<li><a href="https://www.federalreserve.gov/monetarypolicy/fomcminutes20260916.htm">Federal Reserve: FOMC minutes, Sept 2026</a></li>'
                 '<li><a href="https://rateprobability.com/fed">rateprobability.com: Fed rate odds</a></li>'
                 '<li><a href="https://centralbank.watch/federal-reserve/">centralbank.watch: Fed rate probability</a></li></ul>')

    css = CSS + EXTRA_CSS + ".negline{stroke:var(--neg)}.key.negline:before{background:var(--neg)}"
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Market What-Ifs</title>'
            f"<style>{css}</style></head><body><main>{''.join(parts)}</main></body></html>")


if __name__ == "__main__":
    data = json.loads((OUT / "nov4_2026.json").read_text())
    (OUT / "nov4_2026.html").write_text(render(data), encoding="utf-8")
    print(OUT / "nov4_2026.html")
