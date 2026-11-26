import re
from parts import *

src = open("daily_live.html").read()
js = src[src.index("<script>") + 8:src.rindex("</script>")]

# ---- script patches: size charts to their box, readable label sizes, sentence-case chips ----
def sub(old, new, count=None):
    global js
    n = js.count(old)
    assert n, old
    if count is not None:
        assert n == count, (old, n)
    js = js.replace(old, new)

sub("var W=820,H=260,", "var W=cw('chart1'),H=W<560?230:280,")
sub("var W=820,H=200,", "var W=cw('chart2'),H=W<560?190:220,")
sub("var W=820,H=220,", "var W=cw('chart3'),H=W<560?220:250,")
sub("var W=820,H=180,", "var W=cw('chart4'),H=W<560?180:220,")
sub("if(n<=16||i%2===0)", "if(i%lstep(n,W)===0)", 2)
sub('font-size="10.5"', 'font-size="12"')
sub('font-size="11"', 'font-size="12"')
for a in ("11px", "11.5px", "12px", "12.5px"):
    js = js.replace("font-size:" + a, "font-size:13px")
sub("<div style=\"font-size:13px;color:var(--d2);margin-top:8px;text-transform:uppercase;letter-spacing:.08em\">What changed</div>",
    "<h3 style=\"font-size:14px;margin:14px 0 4px\">What changed</h3>")
sub('<span class="phase" style="display:inline-block;font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:2px 8px;border-radius:20px;background:var(--viobg);color:var(--vio)">',
    '<span class="phase">')
sub("function svg(w,h,body){",
    "function cw(id){var e=$(id),w=e?e.clientWidth:0;return Math.max(300,Math.round(w||820))}\n"
    "function lstep(n,W){return Math.max(1,Math.ceil(n*46/Math.max(1,W-70)))}\n"
    "function svg(w,h,body){")
# redraw charts when the column width changes (phone rotate, chat pane resize)
sub("var mq;try{",
    "var lastW=0,rz;try{new ResizeObserver(function(){var w=document.querySelector('main').clientWidth;if(Math.abs(w-lastW)<8)return;lastW=w;clearTimeout(rz);rz=setTimeout(function(){chart1();chart2();chart3();renderBook()},120)}).observe(document.querySelector('main'))}catch(e){}\n"
    "var mq;try{")

page_css = """
/* Desk Daily: lead row (the latest read + four figures), then sections in the shared pattern */
.strip{margin:0 0 22px}
.lead{display:grid;gap:22px 32px;grid-template-columns:minmax(0,1fr)}
.lead .sec{margin-top:0}
@media (min-width:900px){.lead{grid-template-columns:minmax(0,1fr) minmax(0,1.25fr);align-items:start}}
.now{background:var(--lead);border:none;border-radius:6px;padding:20px 22px;margin:0}
.now .phase{margin-right:8px}
.now .sum{font-size:clamp(19px,2.2vw,23px);font-weight:600;line-height:1.38;letter-spacing:-.01em;margin:10px 0 10px}
.now ul{margin:4px 0 0;padding-left:18px;font-size:15px;color:var(--dim)}.now li{margin-bottom:4px}
.now b{font-weight:700}
.days{display:flex;gap:6px;overflow-x:auto;padding-bottom:6px;margin-bottom:12px}
.days button{font-size:14px;cursor:pointer;background:var(--p2);color:var(--dim);border:1px solid transparent;border-radius:4px;padding:8px 11px;white-space:nowrap;font-variant-numeric:tabular-nums;min-height:40px}
.days button:hover{color:var(--tx)}
.days button[aria-pressed="true"]{color:var(--bg);background:var(--vio);font-weight:600}
.dv h3:first-child{margin-top:0}
.dv ul{margin:0;padding-left:18px;font-size:15px}.dv li{margin-bottom:5px}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--line);border-block:1px solid var(--line);margin-bottom:12px}
.kv div{background:var(--p1);padding:9px 10px 9px 0;font-size:13px;color:var(--dim)}
.kv b{display:block;color:var(--tx);font-size:17px;font-weight:700;font-variant-numeric:tabular-nums}
"""

T = lambda k, s: f'<div class="tile"><div class="k">{k}</div><div class="v">–</div><div class="s">{s}</div></div>'

def sec(id, nav, h, n, body):
    return (f'<section class="sec" id="{id}" data-nav="{nav}">\n<header class="sec-h"><h2>{h}</h2><p class="sec-n">{n}</p></header>\n'
            f'{body}\n</section>\n')

body = masthead("daily", "Desk Daily",
    'What the desk thinks today, how its calls have scored, and the context around them. Written by scheduled runs before the open (about 8:47 ET), at midday if something breaks and after the close (about 4:47 ET). Every call is graded in the <a href="https://claude.ai/artifact/7jU3VUdjX9x22fNqXoYbCL" target="_blank" rel="noopener">Desk Ledger</a>.')
body += JUMPBAR
body += '<main class="gut">\n'
tiles = ('<div class="tiles strip" id="tiles">' + T("S&amp;P 500", "last close") + T("VIX", "last close")
         + T("Desk vs formula", "Brier, lower is better") + T("Moves vs VIX promise", "realized ÷ implied vol") + '</div>\n')
body += tiles
body += '<div class="lead">\n<div class="card now" id="now"><span class="phase">Waiting</span><div class="sum mut">The latest desk read appears here.</div></div>\n'
body += sec("range", "Range", "The S&amp;P against the desk's range", "Daily high to low, the close, and the desk's 80% band",
    '<div id="chart1"></div>\n<div class="legend"><span><i style="background:var(--viobg);border:1px solid var(--vio)"></i>Desk 80% band</span><span><i style="background:var(--d2)"></i>High to low</span><span><i style="background:var(--blu)"></i>Close inside band</span><span><i style="background:var(--red)"></i>Close outside band</span></div>\n<p class="note" id="bandnote"></p>')
body += '</div>\n'
body += sec("options", "Options", "Options lens", "Did the S&amp;P move more than the VIX priced?",
    '<div class="card"><div id="chart2"></div>\n<div class="legend"><span><i style="background:var(--d2)"></i>Move the VIX priced (1 day, ±1σ)</span><span><i style="background:var(--amb)"></i>Actual move, bigger</span><span><i style="background:var(--blu)"></i>Actual move, smaller</span></div>\n<p class="note" id="optnote"></p></div>')
body += sec("calibration", "Calibration", "Calibration", "When the desk said X%, how often it happened",
    '<div class="card"><div id="chart3"></div><p class="note" id="calnote"></p></div>')
body += sec("forecasters", "Forecasters", "Three forecasters", "Who has earned the most weight",
    '<div class="card tw"><table id="fc"></table><p class="note" id="fcnote"></p></div>')
body += sec("regime", "Regime", "Regime", "What kind of market each day was, and how the desk does in each",
    '<div class="card"><div id="regnow"></div><div class="tw" style="margin-top:10px"><table id="regtab"></table></div></div>')
body += sec("flows", "Flows", "Flows and positioning", "Who is leaning which way, and what must trade at the close",
    '<div class="tiles" id="flowtiles">' + T("Lev-ETF close hedge", "Nasdaq-100, per 1% move") + T("SPY flows, 5 days", "creations minus redemptions")
    + T("Hedge funds, S&amp;P futures", "percentile of 3 years") + T("Margin debt", "FINRA, month-end") + '</div>\n'
    '<div class="card"><div id="flowflags"></div><div class="tw"><table id="cot"></table></div>\n<p class="note" id="flownote"></p></div>')
body += sec("credit", "Credit", "Credit and funding", "Are lenders getting nervous, and is money tight?",
    '<div class="tiles" id="credtiles">' + T("High-yield spread", "ICE BofA, over Treasuries") + T("Weakest credits (CCC)", "extra yield over BB")
    + T("SOFR vs IORB", "repo funding pressure") + T("Deal flow", "SEC prospectus filings") + '</div>\n'
    '<div class="card"><div id="credflags"></div><div id="creddiv" style="font-size:15px;margin-bottom:12px"></div><div class="tw"><table id="credtab"></table></div>\n<p class="note" id="crednote"></p></div>\n'
    '<div class="card"><h3 style="margin-top:0">Treasury auctions: did buyers show up?</h3>\n<div id="aucflags"></div><div class="tw"><table id="auctab"></table></div><p class="note" id="aucnote"></p></div>')
body += sec("policy", "Policy", "Policy and permitting", "Bills and rules that could move sectors",
    '<div class="tiles" id="poltiles">' + T("Texas bills filed", "90th session, since 9 Nov") + T("Touch markets", "tagged by theme")
    + T("Session opens", "Texas Legislature") + T("Federal rules, 7 days", "energy, permitting, markets agencies") + '</div>\n'
    '<div class="card"><div id="polflags"></div><div id="poltheme" class="mut" style="font-size:14px;margin-bottom:8px"></div>\n'
    '<div class="tw"><table id="poltx"></table></div><div class="tw" style="margin-top:12px"><table id="polfr"></table></div>\n<p class="note" id="polnote"></p></div>')
body += sec("book", "Paper book", "Paper book", "Pretend money: would the desk's calls have paid?",
    '<div class="tiles" id="booktiles">' + T("Book value", "started at $10,000") + T("vs holding SPY", "same start date")
    + T("Closed trades", "win rate") + T("Worst drawdown", "peak to trough") + '</div>\n'
    '<div class="card"><div id="chart4"></div>\n<div class="legend"><span><i style="background:var(--vio)"></i>Paper book</span><span><i style="background:var(--d2)"></i>SPY bought and held</span></div>\n'
    '<div class="tw" style="margin-top:12px"><table id="booktab"></table></div>\n'
    '<p class="note">Paper only. Option prices are model estimates (Black-Scholes from the VIX with a skew adjustment and slippage), not market quotes. Rules: defined-risk SPY spreads, at most 2% of the book at risk per trade, one new trade a day, opened only when the desk\'s odds differ from the plain formula by 7 points or more. Not a recommendation to trade.</p></div>')
body += sec("days-sec", "Day by day", "Day by day", "Pick a session",
    '<div class="days" id="days" role="group" aria-label="Pick a trading day"></div>\n<div class="card dv" id="day"><div class="empty">No sessions yet.</div></div>')
body += ('<footer>Formula = a no-judgment forecaster: zero drift, with the daily spread the VIX implies (VIX ÷ √252). The desk has to beat it to earn its keep. '
         'Brier score = average of (probability − outcome)²; a flat 50% guess scores 0.25. Prices: FMP daily data where available, otherwise web sources noted on each day. '
         'Analysis only. <b>Not investment advice</b>, and nothing here recommends any position or trade.</footer>\n</main>\n')

out = ('<title>Desk Daily</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n' + FONT + '\n<style>\n' + theme() + page_css + '</style>\n\n'
       + body + '\n<script>' + js + '</script>\n' + JUMPJS + '\n')
open("desk_daily.html", "w").write(out)
print(len(out))
