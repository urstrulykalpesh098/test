"""Render analyses/output/options_nov9.json -> analyses/output/options_nov9.html (static page)."""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
D = json.loads((ROOT / "output" / "options_nov9.json").read_text())
M, T = D["meta"], {t["id"]: t for t in D["trades"]}
RANK = D["ranking"]

pct = lambda x, d=0: f"{x * 100:.{d}f}%"
sgn = lambda x: f"{'+' if x >= 0 else '−'}${abs(x):.2f}"
cls = lambda x: "up" if x > 0.005 else "dn" if x < -0.005 else ""
WHEN = {"mon_open": "Mon open", "mon_close": "Mon close", "tue_close": "Tue close", "wed_close": "Wed close"}


def ticket(t):
    parts = []
    for q, k, K in t["legs"]:
        side = "Buy" if q > 0 else "Sell"
        parts.append(f"{side} {abs(q)} {int(K)} {'put' if k == 'P' else 'call'}")
    return " · ".join(parts)


def row(i, t):
    return (f"<tr><td class='rk'>{i}</td><td><b>{t['id']} · {html.escape(t['name'])}</b>"
            f"<span class='who'>{html.escape(t['rule'])}</span><span class='who'>{ticket(t)} · SPY 13 Nov</span></td>"
            f"<td class='r'>${t['debit']:.2f}<span class='who'>max ${t['max_debit_for_1to2']:.2f}</span></td>"
            f"<td class='r'>1:{t['reward_risk']:.1f}</td>"
            f"<td class='r'>{t['contracts_for_budget']} × <span class='who'>${t['cash_at_risk']:,.0f} risk / ${t['cash_max_gain']:,.0f} max</span></td>"
            f"<td class='r'>{pct(t['trigger_rate'])}</td>"
            f"<td class='r'>{pct(t['p_profit'])}</td>"
            f"<td class='r'>{pct(t['p_beyond_long_strike_options'])} / {pct(t['p_beyond_long_strike_sim'])}</td>"
            f"<td class='r {cls(t['ev_per_dollar_risked'])}'>{t['ev_per_dollar_risked']:+.2f}</td>"
            f"<td class='r {cls(t['ev_if_25pct_richer'])}'>{t['ev_if_25pct_richer']:+.2f}</td></tr>")


top, alt = T[RANK[0]], T[RANK[1]]
uncond = [t for t in (T[k] for k in RANK) if t["trigger_rate"] > 0.99 and t["ev_if_25pct_richer"] > 0]
pick = uncond[0] if uncond else top
other = top if pick is not top else alt

CSS = """
:root{--bg:#0b0e13;--p1:#141922;--p2:#1b212c;--line:#262e3b;--l2:#1c222c;--tx:#e9eff7;--dim:#8d9aab;--d2:#66738a;
--red:#f0565e;--grn:#3fb950;--amb:#e3a008;--blu:#6ea8fe;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color-scheme:dark}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--bg:#f5f7fa;--p1:#fff;--p2:#eef1f6;--line:#d8dee8;--l2:#e6eaf1;--tx:#121a26;--dim:#526077;--d2:#76839a;--red:#cf2f38;--grn:#1f8a3a;--amb:#a86f00;--blu:#2f6fdc;color-scheme:light}}
:root[data-theme="light"]{--bg:#f5f7fa;--p1:#fff;--p2:#eef1f6;--line:#d8dee8;--l2:#e6eaf1;--tx:#121a26;--dim:#526077;--d2:#76839a;--red:#cf2f38;--grn:#1f8a3a;--amb:#a86f00;--blu:#2f6fdc;color-scheme:light}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.6 var(--sans)}
main{max-width:900px;margin:0 auto;padding-block:20px 72px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
.kick{font-size:10.5px;letter-spacing:.15em;text-transform:uppercase;color:var(--d2)}
h1{font-size:24px;margin:5px 0 4px;letter-spacing:-.025em;line-height:1.2;text-wrap:balance}
.stamp{color:var(--d2);font-size:12px;margin-bottom:18px}
h2{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin:32px 0 12px;padding-bottom:7px;border-bottom:1px solid var(--line)}
p{margin:0 0 12px}b{font-weight:640}.mut{color:var(--dim)}.sm{font-size:13px}
.card{background:var(--p1);border:1px solid var(--line);border-radius:11px;padding:14px 15px;margin-bottom:12px}
.warn{border-left:3px solid var(--amb)}.pick{border-left:3px solid var(--blu)}
.ticket{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:10px 0}
.ticket div{background:var(--p2);border:1px solid var(--line);border-radius:8px;padding:9px 10px}
.ticket .k{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--d2)}
.ticket .v{font-size:17px;font-weight:680;font-variant-numeric:tabular-nums;margin-top:2px}
.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:12.8px}
th{text-align:left;font-size:9.8px;text-transform:uppercase;letter-spacing:.07em;color:var(--d2);font-weight:600;padding:0 8px 7px 0;border-bottom:1px solid var(--line);vertical-align:bottom}
td{padding:9px 8px 9px 0;border-bottom:1px solid var(--l2);vertical-align:top}tr:last-child td{border-bottom:none}
th.r,td.r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td .who{display:block;font-size:11.3px;color:var(--d2);line-height:1.4;margin-top:2px;white-space:normal}
td.rk{color:var(--d2);font-variant-numeric:tabular-nums}
.up{color:var(--grn)}.dn{color:var(--red)}
ul{margin:0;padding-left:18px}li{margin-bottom:7px}
footer{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);color:var(--d2);font-size:11.5px;line-height:1.65}
"""


def ticket_card(t, title):
    return f"""<div class="card pick"><b>{title}: {t['id']} · {html.escape(t['name'])}</b>
<p class="sm mut" style="margin:4px 0 0">{html.escape(t['thesis'])}</p>
<div class="ticket">
<div><div class="k">When</div><div class="v" style="font-size:14px">{html.escape(t['rule'])}</div></div>
<div><div class="k">Ticket (SPY, expires Fri 13 Nov)</div><div class="v" style="font-size:14px">{ticket(t)}</div></div>
<div><div class="k">Estimated cost</div><div class="v">${t['debit']:.2f}</div></div>
<div><div class="k">Pay no more than</div><div class="v">${t['max_debit_for_1to2']:.2f}</div></div>
<div><div class="k">Size for $2,000</div><div class="v">{t['contracts_for_budget']} spreads</div></div>
<div><div class="k">Risk / best case</div><div class="v">${t['cash_at_risk']:,.0f} / ${t['cash_max_gain']:,.0f}</div></div>
<div><div class="k">Wins in simulation</div><div class="v">{pct(t['p_profit'])}</div></div>
<div><div class="k">Loses everything</div><div class="v">{pct(t['p_lose_all'])}</div></div>
</div></div>"""


page = f"""<title>Option Trade Lab</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>{CSS}</style>
<main>
<div class="kick">Options · week of 9–13 Nov 2026 · tested against {M['runs']} simulated weeks</div>
<h1>Ten defined-risk trades, and the one that holds up</h1>
<div class="stamp">Built Sun 8 Nov · SPY Friday ≈ ${M['spy_friday']:.2f} · 200-day ≈ ${M['spy_ma200']:.2f} · budget $2,000 · every trade at least 1:2 reward to risk</div>

<div class="card warn"><b>Read this first. There is no hard evidence here, and I won't pretend otherwise.</b>
<ul class="sm" style="margin-top:8px">
<li><b>No real option prices were available.</b> Alpha Vantage's option chains are a paid endpoint, FMP has none, and the Cboe chains in your readiness report only work through your Mac's browser. Every price below is a <b>model estimate</b> (Black-Scholes, anchored to VIX 25.64, with an assumed put skew of {M['put_skew']} vol points per 1% out of the money).</li>
<li><b>"Edge" means my simulation disagrees with my option model.</b> Both rest on my assumptions. That is a hypothesis to test, not proof the market is mispriced.</li>
<li><b>1:2 is not the same as good.</b> A 1:2 trade that wins 25% of the time loses money. The column that matters is expected value per $1 risked, and whether it survives options costing 25% more than my model says.</li>
<li><b>Each trade has a hard check you can make on Monday:</b> the most you can pay and still have 1:2. If the live price is above it, the trade fails your own rule. Skip it.</li>
</ul></div>

<h2>If you do only one</h2>
{ticket_card(pick, 'The one that holds up')}
<div class="card sm"><b>Why this one.</b> It is the only trade you can place on Monday without waiting for news that still has positive expected value when options cost 25% more than my model ({pick['ev_if_25pct_richer']:+.2f} per $1 risked; {pick['ev_per_dollar_risked']:+.2f} at model prices). The option model gives SPY a {pct(pick['p_beyond_long_strike_options'])} chance of finishing below the long strike, against {pct(pick['p_beyond_long_strike_sim'])} in the simulation. That gap comes from the mechanics in your reports: the rising 200-day, trend followers flipping, and vol-target selling.
<br><br><b>How thin it is.</b> The estimated cost of ${pick['debit']:.2f} is only {(1 - pick['debit'] / pick['max_debit_for_1to2']) * 100:.0f}% under the ${pick['max_debit_for_1to2']:.2f} ceiling. If real put skew is steeper than I assumed, the live price will be over the line and the trade is off.
<br><br><b>Handling it.</b> Close it by 3:45pm Friday. Don't hold through expiry, because SPY settling between the strikes risks assignment on the short put. This test only covered holding to Friday; early profit-taking wasn't tested. The worst case is losing the full ${pick['cash_at_risk']:,.0f}, which happens in {pct(pick['p_lose_all'])} of simulated weeks.</div>
{ticket_card(other, 'If you would rather wait for Tuesday')}
<div class="card sm">Highest expected value of the ten ({other['ev_per_dollar_risked']:+.2f} per $1, {other['ev_if_25pct_richer']:+.2f} if options are 25% richer), but it only exists after a hot CPI, which I put at {pct(other['trigger_rate'])}. Strikes are set from Tuesday's closing price: about 1% and 2% below it. If CPI is not hot, there is no trade.</div>

<h2>All ten, ranked</h2>
<div class="card tw"><table>
<thead><tr><th>#</th><th>Trade</th><th class="r">Est. cost</th><th class="r">Reward:risk</th><th class="r">Size for $2k</th><th class="r">Setup occurs</th><th class="r">Wins</th><th class="r">Beyond long strike<br>options / sim</th><th class="r">EV per $1</th><th class="r">EV if 25%<br>pricier</th></tr></thead>
<tbody>{''.join(row(i + 1, T[k]) for i, k in enumerate(RANK))}</tbody></table></div>
<p class="sm mut">"Setup occurs": the share of simulated weeks where the entry condition is met. "Wins": the chance it finishes with any profit, once entered. "Beyond long strike": the chance of SPY finishing past the bought strike, by the option model and by the simulation. The gap between the two is the whole case for each trade.</p>

<h2>What the ten taught</h2>
<div class="card sm"><ul>
<li><b>Upside bets lose in this simulation.</b> Call spreads and the call butterfly have negative expected value, because the simulated week leans lower and has a fatter downside tail. The options price that downside tail too, so buying calls is not where the gap is.</li>
<li><b>Waiting for confirmation costs more than it earns.</b> Buying puts after a confirmed 200-day break (T2) is worse than buying before it (T1). By Monday's close, the move and the higher volatility are already in the price.</li>
<li><b>Butterflies are cheap but rarely pay in full.</b> 1:9 reward to risk sounds great, but SPY has to finish close to one exact strike. They almost never pay the maximum.</li>
<li><b>The one real gap is the 200-day mechanics, and it is small.</b> It shows up as a few points of probability, which a steeper real skew could erase.</li>
</ul></div>

<h2>Monday checklist</h2>
<div class="card sm"><ul>
<li>Get the live bid and ask for both legs of the spread. Use the mid as your limit, and never pay more than the "pay no more than" figure.</li>
<li>If the spread between bid and ask on either leg is wider than about $0.10, the slippage assumption fails. Recheck the numbers.</li>
<li>Compare the real implied vol of the 730 put with the model's (about {25.64 + 0.9 * 0.85:.0f}% here). If it is much higher, puts are pricier than modelled and the gap is smaller.</li>
<li>Don't enter in the first 15 minutes. Spreads are widest right after the open.</li>
<li>Size so the full loss is money you can lose. Defined-risk spreads can and often do expire worthless.</li>
</ul></div>

<h2>Not tested, and why</h2>
<div class="card sm"><ul>
<li><b>Single stocks</b> (CoreWeave, Nvidia, the chip ETFs): there's no option data for them here, and the simulation only models the index. Your reports say CoreWeave's options price about a 9-point move and Nvidia's about ±8.5%, with Nvidia beating its implied move only ~29% of the time. Selling that premium needs more margin than $2,000 allows.</li>
<li><b>Expiries after 13 Nov:</b> valuing them on Friday would need an assumption about future volatility on top of everything else.</li>
<li><b>Early exits and stop-losses:</b> every trade here is held to Friday.</li>
</ul></div>

<footer>Model and code: <span>analyses/options_nov9.py</span> in urstrulykalpesh098/test, using the 9 Nov week simulation (12 paths, 604 runs). Pricing assumptions: VIX 25.64 at Monday's open; after CPI the at-the-money vol resets to 27% hot, 22% in line, 20% cool; +2 points after a bad CoreWeave; vol rises 2.5 points per 1% fall; ${M['slippage_per_leg']:.2f} slippage per leg; rates 3.9%, dividend yield 1.2%.
This is analysis of a simulation, not investment advice and not a recommendation to trade. Options can lose 100% of what you pay.</footer>
</main>"""
out = ROOT / "output" / "options_nov9.html"
out.write_text(page, encoding="utf-8")
print(out, "pick", pick["id"], "other", other["id"])
