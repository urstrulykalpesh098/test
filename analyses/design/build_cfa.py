from parts import *

src = open("cfa_live.html").read()
css = src[src.index("<style>", src.index("</head>")) + 7:src.index("</style>", src.index("</head>"))]
js = src[src.index("<script>") + 8:src.rindex("</script>")]

css = css.replace('"Space Grotesk",system-ui,sans-serif', 'var(--sans)').replace('"Space Grotesk",sans-serif', 'var(--sans)')
css = css.replace("Inter,system-ui,sans-serif", "var(--sans)").replace("Inter,sans-serif", "var(--sans)")
css = css.replace("font:600 ", "font:700 ")
# answer-sheet colours moved onto the desk palette: teal marks, claret for a wrong mark
css = css.replace(":root{color-scheme:light dark;--bg:light-dark(#ffffff,#0b1310);--ink:light-dark(#121614,#e8efe9);--mute:light-dark(#56615a,#9fb0a5);--line:light-dark(#cfe3d6,#22382b);--green:light-dark(#0a7d4f,#3ccf8e);--mist:light-dark(#eaf6ef,#12241a);--coral:light-dark(#d6452b,#ff7a5c);--coralmist:light-dark(#fdece8,#2a1510)}",
    ":root{color-scheme:light dark;--ink:light-dark(#14181b,#e8eff0);--mute:light-dark(#4f5a61,#a3b3b7);--green:light-dark(#0d7680,#4fc3c9);--mist:light-dark(#e7f1f1,#10292c);--coral:light-dark(#b3123f,#ff6f8e);--coralmist:light-dark(#fbe9ee,#2a1519)}")
assert "--green:light-dark(#0d7680" in css
css = css.replace("body{background:var(--bg);color:var(--ink);font:16px/1.55 var(--sans);overflow-x:clip;margin:0}", "body{color:var(--ink)}")
css += """
/* CFA card on the desk masthead */
.mast .gut,.wrap{max-width:820px}
.wrap{padding-left:max(5vw,16px,env(safe-area-inset-left,0px));padding-right:max(5vw,16px,env(safe-area-inset-right,0px))}
.wk{display:inline-flex;align-items:center;gap:10px;margin-top:14px;font-size:15px;color:var(--banddim)}
.wk select{background:transparent;color:var(--bandtx);border:1.5px solid rgba(255,255,255,.35);border-radius:4px;font:16px var(--sans);padding:8px 10px}
.wk select option{color:#14181b;background:#fff}
.dot,.ch .b,.btn,.card,.ch,.week,.verdict,.rev,.bx,.num input,select{border-radius:6px}
.dot,.ch .b{border-radius:50%}
.card{margin-bottom:0}
.wrap{padding-block:22px 56px}
.week{margin-top:0}
"""

body = masthead("cfa", "CFA weekly card",
    "This week's market, turned into Level I questions. Answer first, then read the working. Missed questions come back for review.",
    status=False, extra='<label class="wk">Week <select id="wk" aria-label="Week"></select></label>')
body += ('<div class="wrap">\n  <div id="main"><div class="empty" id="msg">Loading this week\'s card…</div></div>\n'
         '  <footer>Built from the Eye View desk\'s own records (Desk Daily and Desk Ledger); each answer names its source. Topic areas follow the CFA Level I curriculum; '
         'check reading names against your own exam year. <b>Not investment advice.</b></footer>\n</div>\n')

out = ('<title>CFA Weekly Card</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n' + FONT + '\n<style>\n' + theme() + css + '</style>\n\n'
       + body + '\n<script>' + js + '</script>\n')
open("cfa_weekly_card.html", "w").write(out)
print(len(out))
