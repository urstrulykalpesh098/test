"""Eye View data backbone: pull free official daily history into one place.

Every desk run should read these files instead of guessing closes from web snippets.
Stdlib only. Source: FRED (fredgraph.csv, no key). Writes
  analyses/data/history/<SERIES>.csv   date,value  (missing days dropped)
  analyses/data/history/manifest.json  per series: name, group, first, last, rows, fetched_at, status

A failed fetch never deletes data: the old file is kept and the manifest marks it stale.
Usage: python analyses/backbone/pull.py [--only SP500,VIXCLS] [--out DIR]
Not investment advice; analysis only.
"""
import argparse, csv, io, json, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "history"
UA = "curl/8.5.0"  # FRED stalls on browser-like and unknown agents; a curl agent works

# id: (plain name, group)
SERIES = {
    "SP500": ("S&P 500 index close", "equity"),
    "NASDAQCOM": ("Nasdaq Composite close", "equity"),
    "DJIA": ("Dow Jones Industrial Average close", "equity"),
    "VIXCLS": ("VIX close (30-day implied vol)", "vol"),
    "VXVCLS": ("VIX 3-month close", "vol"),
    "DGS3MO": ("3-month Treasury yield", "rates"),
    "DGS2": ("2-year Treasury yield", "rates"),
    "DGS10": ("10-year Treasury yield", "rates"),
    "DGS30": ("30-year Treasury yield", "rates"),
    "T10Y2Y": ("10y minus 2y spread", "rates"),
    "T10YIE": ("10-year breakeven inflation", "rates"),
    "DFII10": ("10-year real yield (TIPS)", "rates"),
    "SOFR": ("SOFR overnight rate", "funding"),
    "DFF": ("Effective fed funds rate", "funding"),
    "DFEDTARU": ("Fed funds target, upper bound (changes mark rate decisions)", "funding"),
    "RRPONTSYD": ("Fed overnight reverse repo usage ($bn)", "funding"),
    "WALCL": ("Fed balance sheet total assets ($mn, weekly)", "funding"),
    "BAMLH0A0HYM2": ("US high-yield OAS", "credit"),
    "BAMLC0A0CM": ("US investment-grade OAS", "credit"),
    "NFCI": ("Chicago Fed financial conditions (weekly)", "credit"),
    "STLFSI4": ("St. Louis Fed financial stress (weekly)", "credit"),
    "DTWEXBGS": ("Broad trade-weighted US dollar", "fx"),
    "DEXCAUS": ("CAD per USD", "fx"),
    "DEXUSEU": ("USD per EUR", "fx"),
    "DEXJPUS": ("JPY per USD", "fx"),
    "DCOILWTICO": ("WTI crude oil spot", "commodity"),
    "DCOILBRENTEU": ("Brent crude oil spot", "commodity"),
    "DHHNGSP": ("Henry Hub natural gas spot", "commodity"),
}


def parse_fred_csv(text):
    """Return [(date, float)] from a fredgraph.csv body, skipping '.' and blanks."""
    rows = []
    r = csv.reader(io.StringIO(text))
    header = next(r, None)
    if not header or len(header) < 2:
        raise ValueError("no header")
    for line in r:
        if len(line) < 2:
            continue
        d, v = line[0].strip(), line[1].strip()
        if not v or v == ".":
            continue
        try:
            datetime.strptime(d, "%Y-%m-%d")
            rows.append((d, float(v)))
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
                return parse_fred_csv(resp.read().decode("utf-8", "replace"))
        except Exception as e:  # network or parse
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{sid}: {last}")


def read_csv(path):
    if not path.exists():
        return []
    with open(path, newline="") as f:
        r = csv.reader(f)
        next(r, None)
        return [(a, float(b)) for a, b in r]


def merge(old, new):
    """Union by date; new values win (FRED revises some series)."""
    m = dict(old)
    m.update(dict(new))
    return sorted(m.items())


def write_csv(path, rows):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "value"])
        for d, v in rows:
            w.writerow([d, repr(v) if v != int(v) else f"{v:.1f}"])
    tmp.replace(path)


def run(only=None, out=OUT, fetcher=fetch):
    out.mkdir(parents=True, exist_ok=True)
    mpath = out / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ok = bad = 0
    for sid, (name, group) in SERIES.items():
        if only and sid not in only:
            continue
        path = out / f"{sid}.csv"
        entry = manifest.get(sid, {})
        try:
            rows = merge(read_csv(path), fetcher(sid))
            if not rows:
                raise RuntimeError("empty")
            write_csv(path, rows)
            entry.update(name=name, group=group, source="FRED", first=rows[0][0],
                         last=rows[-1][0], rows=len(rows), fetched_at=now, status="ok")
            entry.pop("error", None)
            ok += 1
        except Exception as e:
            entry.update(name=name, group=group, source="FRED", status="stale", error=str(e)[:200])
            bad += 1
        manifest[sid] = entry
        print(f"{sid:14s} {entry.get('status'):5s} last={entry.get('last')} rows={entry.get('rows')}")
    mpath.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(f"done: {ok} ok, {bad} stale")
    return ok, bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    ok, bad = run(set(a.only.split(",")) if a.only else None, Path(a.out))
    sys.exit(0 if ok else 1)
