"""Inject analyses/output/monday_nov9.json into the replay template -> analyses/output/monday_replay.html"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
data = (ROOT / "output" / "monday_nov9.json").read_text().replace("</", "<\\/")
html = (ROOT / "monday_replay_template.html").read_text().replace("__DATA__", data)
out = ROOT / "output" / "monday_replay.html"
out.write_text(html, encoding="utf-8")
print(out)
