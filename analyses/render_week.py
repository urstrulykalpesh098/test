"""Inject analyses/output/week_nov9.json into the week template -> analyses/output/week_nov9.html"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
data = (ROOT / "output" / "week_nov9.json").read_text().replace("</", "<\\/")
html = (ROOT / "week_template.html").read_text().replace("__DATA__", data)
out = ROOT / "output" / "week_nov9.html"
out.write_text(html, encoding="utf-8")
print(out)
