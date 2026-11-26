"""One command for the whole next-level stack, in order:
pull data -> lab studies -> analysts -> multi-asset calls (grade + new) -> playbooks
-> research loop (Sundays, or --research) -> hub data file for the Eye View HQ page.

    python analyses/backbone/nightly.py [--no-pull] [--research]

Writes analyses/output/hub/hub_data.json (everything the HQ page shows).
Not investment advice; analysis only.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from analyses.backbone import pull  # noqa: E402
from analyses.backbone.history import manifest  # noqa: E402
from analyses.lab import lab, analysts, multiasset, playbook, research, ranges  # noqa: E402

HUB = ROOT / "analyses" / "output" / "hub" / "hub_data.json"


def build_hub(res):
    m = manifest()
    return {
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backbone": {k: {x: v.get(x) for x in ("name", "group", "first", "last", "rows", "status")} for k, v in sorted(m.items())},
        "lab": res["lab"], "analysts": res["analysts"], "multiasset": res["multiasset"],
        "playbook": res["playbook"], "research": res["research"], "ranges": res["ranges"],
        "disclaimer": "Analysis only. Not investment advice.",
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pull", action="store_true")
    ap.add_argument("--research", action="store_true", help="run the research loop even if it is not Sunday")
    a = ap.parse_args(argv)
    if not a.no_pull:
        ok, bad = pull.run()
        if not ok:
            print("no data pulled; stopping")
            return 1
    res = {"lab": lab.run(), "analysts": analysts.run(), "multiasset": multiasset.run(), "playbook": playbook.run(), "ranges": ranges.run()}
    latest = ROOT / "analyses" / "output" / "research" / "latest.json"
    if a.research or datetime.now(timezone.utc).weekday() == 6 or not latest.exists():
        res["research"] = research.run()
    else:
        res["research"] = json.loads(latest.read_text())
    HUB.parent.mkdir(parents=True, exist_ok=True)
    HUB.write_text(json.dumps(build_hub(res), separators=(",", ":")) + "\n")
    print("hub data:", HUB, HUB.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
