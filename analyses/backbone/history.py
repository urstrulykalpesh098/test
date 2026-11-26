"""Read the backbone history files. Stdlib only.

    from analyses.backbone.history import load, aligned
    spx = load("SP500")            # {date: value}
    rows = aligned("SP500","VIXCLS")  # [(date, spx, vix)] on days both exist
"""
import csv, json
from pathlib import Path

HIST = Path(__file__).resolve().parents[1] / "data" / "history"


def load(sid, hist=HIST):
    with open(Path(hist) / f"{sid}.csv", newline="") as f:
        r = csv.reader(f)
        next(r, None)
        return {d: float(v) for d, v in r}


def aligned(*sids, hist=HIST):
    data = [load(s, hist) for s in sids]
    common = sorted(set(data[0]).intersection(*data[1:]))
    return [(d, *[x[d] for x in data]) for d in common]


def manifest(hist=HIST):
    return json.loads((Path(hist) / "manifest.json").read_text())


def asof(series, date):
    """Last value on or before date from a {date: value} dict (for weekly series)."""
    best = None
    for d in sorted(series):
        if d > date:
            break
        best = series[d]
    return best
