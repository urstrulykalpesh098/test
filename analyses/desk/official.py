"""Official S&P 500 and VIX closes for grading, from FRED (free, primary).

The close scorecard used to grade calls from web search snippets, which often
disagree (25 Nov 2026: "VIX close unverified 28.04/28.64/31.72"). From desk v2.9
S&P and VIX calls are graded only on these numbers. FRED posts a day's close the
next morning or so, so a call that resolves today is graded by the next close run.

    python3 official.py [--days 30] [--out official.json]

Prints the last few closes and writes {"source", "fetched_at", "closes": {date: {sp, vix, vxv}},
"latest": {...}, "missing": [...]}. Stored in Desk Ledger method/official_script.
Stdlib only, single file. Analysis only.
"""
import argparse, csv, io, json, sys, time, urllib.request
from datetime import datetime, timezone

VERSION = "1.0"
UA = "curl/8.5.0"  # FRED stalls on browser-like and unknown agents
SERIES = {"sp": "SP500", "vix": "VIXCLS", "vxv": "VXVCLS"}


def parse(text):
    rows = []
    r = csv.reader(io.StringIO(text))
    next(r, None)
    for line in r:
        if len(line) < 2 or not line[1].strip() or line[1].strip() == ".":
            continue
        try:
            datetime.strptime(line[0].strip(), "%Y-%m-%d")
            rows.append((line[0].strip(), float(line[1])))
        except ValueError:
            continue
    return rows


def fetch(sid, tries=3):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return parse(resp.read().decode("utf-8", "replace"))
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{sid}: {last}")


def build(series_rows, days=30):
    closes, missing = {}, []
    for key, rows in series_rows.items():
        if rows is None:
            missing.append(SERIES[key])
            continue
        for d, v in rows[-days:]:
            closes.setdefault(d, {})[key] = v
    ds = sorted(closes)
    out = {"version": VERSION, "source": "FRED (" + ", ".join(SERIES.values()) + ")",
           "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "closes": {d: closes[d] for d in ds}, "missing": missing}
    for k in SERIES:
        have = [d for d in ds if k in closes[d]]
        if have:
            d = have[-1]
            prev = have[-2] if len(have) > 1 else None
            out.setdefault("latest", {})[k] = {"date": d, "close": closes[d][k],
                                               "prev_date": prev, "prev": closes[prev][k] if prev else None}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rows = {}
    for k, sid in SERIES.items():
        try:
            rows[k] = fetch(sid)
        except Exception as e:
            print("FAILED", e, file=sys.stderr)
            rows[k] = None
    out = build(rows, a.days)
    if a.out:
        open(a.out, "w").write(json.dumps(out, indent=1))
    for d in list(out["closes"])[-5:]:
        print(d, out["closes"][d])
    if out["missing"]:
        print("missing:", ", ".join(out["missing"]))
    return 0 if not out["missing"] else 2


if __name__ == "__main__":
    sys.exit(main())
