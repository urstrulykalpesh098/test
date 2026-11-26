"""Build desk_guide.html (the plain-language desk guide page) from the shared desk theme,
guide.css and guide_body.html. Usage: python analyses/output/guide/build.py"""
from pathlib import Path
here = Path(__file__).resolve().parent
theme = (here.parents[1] / "design" / "desk_theme.css").read_text()
css = (here / "guide.css").read_text()
body = (here / "guide_body.html").read_text()
js = (here / "guide.js").read_text()
head = """<title>Desk Field Guide</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@400;500;600;700;800&display=swap" rel="stylesheet">
"""
out = head + "<style>\n" + theme + "\n" + css + "\n</style>\n" + body + "\n<script>\n" + js + "\n</script>\n"
(here / "desk_guide.html").write_text(out)
print("wrote", here / "desk_guide.html", len(out), "bytes")
