"""One command for the whole next-level stack, in order:
pull data -> lab studies -> multi-asset calls (grade + new) -> playbooks
-> research loop (Sundays, or --research) -> hub data file for the Eye View HQ page.

    python analyses/backbone/nightly.py [--no-pull] [--research] [--with-analysts]

The seven one-feature analysts were archived on 27 Nov 2026 (desk v2.9): over 1,951
out-of-sample days none beat the plain up-rate (all Brier 0.2484-0.2486 vs 0.2484).
Their code (analyses/lab/analysts.py) and last scores (analyses/output/lab/analysts.json)
stay in the repo and the hub shows the archived scores. --with-analysts runs them again.

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
from analyses.deskroom import packets  # noqa: E402
from analyses.godseye import godseye  # noqa: E402

HUB = ROOT / "analyses" / "output" / "hub" / "hub_data.json"


ANALYSTS_JSON = ROOT / "analyses" / "output" / "lab" / "analysts.json"


def archived_analysts():
    """Last scores of the archived analyst panel, marked as archived (not re-run nightly)."""
    try:
        A = json.loads(ANALYSTS_JSON.read_text())
    except (FileNotFoundError, ValueError):
        A = {}
    A["archived"] = {"on": "2026-11-27", "why": "None of the seven beat the plain up-rate over 1,951 out-of-sample days.",
                     "how_to_restore": "python analyses/backbone/nightly.py --with-analysts"}
    return A


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
    ap.add_argument("--with-analysts", action="store_true", help="re-run the archived analyst panel")
    a = ap.parse_args(argv)
    if not a.no_pull:
        ok, bad = pull.run()
        if not ok:
            print("no data pulled; stopping")
            return 1
    res = {"lab": lab.run(), "multiasset": multiasset.run(), "playbook": playbook.run(), "ranges": ranges.run()}
    res["analysts"] = analysts.run() if a.with_analysts else archived_analysts()
    latest = ROOT / "analyses" / "output" / "research" / "latest.json"
    if a.research or datetime.now(timezone.utc).weekday() == 6 or not latest.exists():
        res["research"] = research.run()
    else:
        res["research"] = json.loads(latest.read_text())
    HUB.parent.mkdir(parents=True, exist_ok=True)
    HUB.write_text(json.dumps(build_hub(res), separators=(",", ":")) + "\n")
    print("hub data:", HUB, HUB.stat().st_size, "bytes")
    print("desk room packets:", packets.run())
    try:
        gd = godseye.build()
        gp = ROOT / "analyses" / "output" / "godseye" / "godseye.json"
        gp.parent.mkdir(parents=True, exist_ok=True)
        gp.write_text(json.dumps(gd, separators=(",", ":")))
        print("god's eye view:", gp, gp.stat().st_size, "bytes")
    except Exception as e:  # the map is context only; never fail the nightly run over it
        print("god's eye view skipped:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
