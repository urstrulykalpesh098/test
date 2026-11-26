from parts import *

src = open("ledger_live.html").read()
js = src[src.index("<script>") + 8:src.rindex("</script>")]
js = js.replace(' style="color:var(--blu)"', '')

page_css = """
/* Desk Ledger: figure strip, then due-next beside calibration, then the full record */
.lead{display:grid;gap:22px 32px;grid-template-columns:minmax(0,1fr)}
.lead .sec{margin-top:0}
@media (min-width:900px){.lead{grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);align-items:start}}
.strip{margin:0 0 22px}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.filters button{font-size:14px;cursor:pointer;background:var(--p2);color:var(--dim);border:1px solid transparent;border-radius:4px;padding:8px 13px;min-height:40px}
.filters button:hover{color:var(--tx)}
.filters button[aria-pressed="true"]{background:var(--vio);color:var(--bg);font-weight:600}
.st-open{background:var(--viobg);color:var(--vio)}.st-hit{background:var(--grnbg);color:var(--grn)}.st-miss{background:var(--redbg);color:var(--red)}.st-void{background:var(--p2);color:var(--d2)}
.th-alive{background:var(--grnbg);color:var(--grn)}.th-weakened{background:var(--ambbg);color:var(--amb)}.th-dead{background:var(--redbg);color:var(--red)}.th-confirmed{background:var(--viobg);color:var(--vio)}
.cal{display:grid;gap:12px}
.calrow{display:grid;grid-template-columns:110px minmax(0,1fr) 88px;gap:12px;align-items:center;font-size:14px}
.calbar{position:relative;height:16px;background:var(--p2);border-radius:2px}
.calbar .exp{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--tx)}
.calbar .act{position:absolute;top:0;bottom:0;left:0;border-radius:2px;background:var(--vio)}
@media (max-width:560px){.calrow{grid-template-columns:92px minmax(0,1fr) 74px;gap:8px;font-size:13px}}
.ev{display:grid;grid-template-columns:104px minmax(0,1fr);gap:3px 14px;padding:10px 0;border-bottom:1px solid var(--l2)}
.ev:last-child{border-bottom:none}
.ev .d{font-size:14px;font-weight:700;color:var(--vio);font-variant-numeric:tabular-nums}
.ev .d.past{color:var(--d2);font-weight:500}
.ev .n{font-size:15px;overflow-wrap:anywhere}.ev .w{grid-column:2;font-size:14px;color:var(--dim);overflow-wrap:anywhere}
@media (max-width:480px){.ev{grid-template-columns:84px minmax(0,1fr)}}
.lib{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px 22px;font-size:14px}
.lib a{text-decoration:none;font-weight:500}.lib a:hover{text-decoration:underline}
.lib span{color:var(--d2);font-size:13px}
#method ol{font-size:15px!important}
"""

T = lambda k, s: f'<div class="tile"><div class="k">{k}</div><div class="v">–</div><div class="s">{s}</div></div>'

def sec(id, nav, h, n, body, nid=None):
    nn = f'<p class="sec-n"{f" id=\"{nid}\"" if nid else ""}>{n}</p>'
    return (f'<section class="sec" id="{id}" data-nav="{nav}">\n<header class="sec-h"><h2>{h}</h2>{nn}</header>\n{body}\n</section>\n')

body = masthead("ledger", "Desk Ledger",
    'Every call from every report, with the probability it was given, graded when it resolves. Also the theses the desk is tracking, the lessons it has learned, and the dated catalysts ahead. Updated by the scheduled runs after each US close.')
body += JUMPBAR + '<main class="gut">\n'
body += ('<div class="tiles strip" id="tiles">' + T("Open calls", "waiting to resolve") + T("Resolved", "hits and misses")
         + T("Brier score", "lower is better · coin flip 0.25") + T("Theses alive", "of those tracked") + '</div>\n')
body += '<div class="lead">\n'
body += sec("due-next", "Due next", "Due next", "", '<div class="card tw"><table id="due"></table></div>', nid="duecount")
body += sec("calibration", "Calibration", "Calibration", "When we said X%, how often did it happen?",
    '<div class="card"><div class="cal" id="cal"></div>\n<p class="sm" id="vsbase" style="margin:14px 0 0"></p>\n'
    '<p class="note">Black tick: what was promised (the bucket\'s average probability). Teal bar: what actually happened. Well-calibrated calls put the bar on the tick. Needs about 30 resolved calls before it means much.</p></div>')
body += '</div>\n'
body += sec("calls", "All calls", "All calls", "Probability is what the report said would happen",
    '<div class="filters" id="filters" role="group" aria-label="Filter calls by status">\n'
    '<button type="button" data-f="all" aria-pressed="true">All</button>\n<button type="button" data-f="open" aria-pressed="false">Open</button>\n'
    '<button type="button" data-f="hit" aria-pressed="false">Hit</button>\n<button type="button" data-f="miss" aria-pressed="false">Missed</button>\n</div>\n'
    '<div class="card tw"><table id="preds"></table></div>')
body += sec("theses", "Theses", "Thesis tracker", "Alive until its kill condition shows up", '<div class="card tw"><table id="theses"></table></div>').replace('<section class="sec" id="theses"', '<section class="sec" id="theses-sec"')
body += sec("lessons-sec", "Lessons", "Lessons memory", "Rules the desk has learned, kept only while they keep working", '<div class="card tw"><table id="lessons"></table></div>')
body += sec("method-sec", "Method", "Method notes", "Rewritten each Sunday by the desk's self-review", '<div class="card" id="method"><div class="empty">The first self-review runs Sunday 29 Nov.</div></div>')
body += sec("engine-sec", "Event engine", "Event engine", "Previews and post-mortems for earnings and big data releases",
    '<div class="card"><p class="sm" id="engsum" style="margin:0 0 12px"></p><div class="tw"><table id="engine"></table></div>\n'
    '<p class="note">Implied move = what options priced for the reaction session (source named on each row; "hist" means no options figure was found and the stock\'s own average reaction was used). Baseline = a no-judgment forecaster: for earnings, how often the stock\'s last 8 reactions beat today\'s implied move; for data, how often the last 12 prints beat consensus. Analysis only, not investment advice.</p></div>')
body += sec("calendar", "Calendar", "Calendar", "Dated catalysts from all reports", '<div class="card" id="events"></div>')
body += sec("runs-sec", "Runs", "Desk runs", "What each scheduled run did", '<div class="card tw"><table id="runs"></table></div>')
body += sec("library", "Reports", "Report library", "Every report the desk has written", '<div class="card lib" id="lib"></div>')
body += ('<footer>Scoring: each call is a yes/no event with the probability its report gave. Brier score = average of (probability − outcome)², where outcome is 1 if it happened and 0 if not. '
         '0 is perfect, 0.25 is what always saying 50% earns. Calls without a probability are not scored. Data is written by Claude\'s scheduled desk runs. '
         'Analysis only. <b>Not investment advice</b>, and nothing here recommends any position or trade.</footer>\n</main>\n')

out = ('<title>Desk Ledger</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n' + FONT + '\n<style>\n' + theme() + page_css + '</style>\n\n'
       + body + '\n<script>' + js + '</script>\n' + JUMPJS + '\n')
open("desk_ledger.html", "w").write(out)
print(len(out))
