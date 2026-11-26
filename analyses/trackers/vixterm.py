"""VIX term structure tracker: VIX9D, VIX and VIX3M from Cboe's free daily history files.

Contango (VIX9D < VIX < VIX3M, curve slopes up) is the normal, calm shape: traders pay more
for longer protection. Backwardation (near-term vol above longer-term) means the market is
paying up for protection right now: a stress signal.

Ratios used:
  front = VIX9D / VIX   (above 1: the next 9 days are priced hotter than the next 30)
  main  = VIX / VIX3M   (above 1: backwardation, the classic stress read)

States from main: steep contango < 0.85 <= contango < 0.95 <= flat < 1.00 <= backwardation.
Context only (method/notes rule 12 style): this never moves a probability. Backtest in
analyses/studies/vix_term.py and vix_term_2026-11-26.md: the curve adds real information about
the NEXT WEEK's realized vol beyond VIX level and recent realized vol (out of sample, 2019 on),
but next-day move size gains are small and not significant.

Usage: python vixterm.py [--pull] [--live] [--hist DIR] [--json OUT] [--desk OUT --date D]
  --pull refreshes analyses/data/history/CBOE_{VIX9D,VIX,VIX3M,SPX}.csv (date,value).
  --live reads straight from Cboe without touching files (what the close run's single-file copy does;
         also the automatic fallback when the history files are missing).
  --desk writes {"meta_vixterm", "day_vixterm"} for Desk Daily meta/vixterm and days/<date>.vixterm.
Source: https://cdn.cboe.com/api/global/us_indices/daily_prices/<SYMBOL>_History.csv (no key).
Standard library only. Not investment advice; analysis only.
"""
import argparse, csv, io, json, math, sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from common import get
except ImportError:  # imported as analyses.trackers.vixterm
    from .common import get

HIST = Path(__file__).resolve().parents[1] / "data" / "history"
URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{}_History.csv"
SYMBOLS = ("VIX9D", "VIX", "VIX3M", "SPX")
STATES = ((0.85, "steep contango"), (0.95, "contango"), (1.00, "flat"), (99, "backwardation"))
CAL = {"steep contango": "calm", "contango": "normal", "flat": "tense", "backwardation": "stress"}

# Backtest result (analyses/studies/vix_term_2026-11-26.md), shown with every readout so the
# number is never read without its caveat. Keep in sync when the study is re-run.
FINDING = ("Backtest 2011-2026 (fit 2011-18, scored 2019 on): adding the curve to VIX level and recent "
           "realized vol improved next-5-day realized vol forecasts (R2 0.44 to 0.52, 95% interval clear of zero). "
           "Next-day move size: small gain, not significant. Rule 5 ranges already widen in backwardation and "
           "missed 20% there (on target); flat-curve and hot-front days missed about 28%. Context only.")

# Next-5-day realized vol model, fit on 2011-2018 only (out-of-sample tested 2019 on):
# log(rv5 daily) = a + b*log(VIX) + c*log(rv20 daily) + d*log(VIX/VIX3M) + e*log(VIX9D/VIX)
COEF5 = (-8.442, 1.198, -0.047, 0.75, 0.968)
COEF5_BASE = (-9.962, 1.607, -0.1)  # same without the curve terms


def parse_cboe(text):
    """Cboe CSV (DATE,OPEN,HIGH,LOW,CLOSE or DATE,SPX) -> {iso date: close}."""
    r = csv.reader(io.StringIO(text))
    next(r, None)
    out = {}
    for row in r:
        if len(row) < 2 or not row[0].strip():
            continue
        try:
            d = datetime.strptime(row[0].strip(), "%m/%d/%Y").date().isoformat()
            v = float(row[-1])
        except ValueError:
            continue
        if v > 0:
            out[d] = v
    return out


def fetch_live():
    return {s: parse_cboe(get(URL.format(s), timeout=90)) for s in SYMBOLS}


def pull(hist=HIST):
    hist = Path(hist)
    man_p = hist / "manifest.json"
    man = json.loads(man_p.read_text()) if man_p.exists() else {}
    for s in SYMBOLS:
        key = f"CBOE_{s}"
        try:
            data = parse_cboe(get(URL.format(s), timeout=90))
            if len(data) < 100:
                raise ValueError(f"only {len(data)} rows")
        except Exception as e:  # keep the old file, mark stale
            man.setdefault(key, {})["status"] = f"stale: {e}"[:200]
            print(f"{key}: fetch failed ({e}); kept old file", file=sys.stderr)
            continue
        with open(hist / f"{key}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "value"])
            for d in sorted(data):
                w.writerow([d, data[d]])
        ds = sorted(data)
        man[key] = {"fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "first": ds[0],
                    "last": ds[-1], "rows": len(ds), "group": "vol", "source": "Cboe", "status": "ok",
                    "name": {"VIX9D": "Cboe 9-day VIX close", "VIX": "Cboe VIX close", "VIX3M": "Cboe 3-month VIX close",
                             "SPX": "S&P 500 index close (Cboe file)"}[s]}
    man_p.write_text(json.dumps(man, indent=1, sort_keys=True))


def load(sym, hist=HIST):
    with open(Path(hist) / f"CBOE_{sym}.csv", newline="") as f:
        r = csv.reader(f)
        next(r, None)
        return {d: float(v) for d, v in r}


def series(hist=HIST, live=False):
    if not live:
        try:
            return {s: load(s, hist) for s in SYMBOLS}
        except FileNotFoundError:
            pass
    return fetch_live()


def curve(ser):
    """[(date, vix9d, vix, vix3m)] on days all three exist."""
    a, b, c = ser["VIX9D"], ser["VIX"], ser["VIX3M"]
    return [(d, a[d], b[d], c[d]) for d in sorted(set(a) & set(b) & set(c))]


def week_vol(ser, d, v9, v, v3):
    """Expected next-5-day S&P realized vol (annualized %), with and without the curve terms."""
    spx = ser.get("SPX") or {}
    ds = [x for x in sorted(spx) if x <= d][-21:]
    if len(ds) < 21 or ds[-1] != d:
        return None
    r = [math.log(spx[b] / spx[a]) for a, b in zip(ds, ds[1:])]
    rv20 = math.sqrt(sum(x * x for x in r) / 20)
    xb = [1, math.log(v), math.log(max(rv20, 1e-5))]
    x = xb + [math.log(v / v3), math.log(v9 / v)]
    ann = lambda c, xs: round(100 * math.sqrt(252) * math.exp(sum(a * b for a, b in zip(c, xs))), 1)
    return {"with_curve": ann(COEF5, x), "without_curve": ann(COEF5_BASE, xb), "vix": v,
            "realized_20d": round(100 * math.sqrt(252) * rv20, 1),
            "note": "median-type estimate (log model); actual weeks scatter widely around it"}


def state_of(main):
    for cut, name in STATES:
        if main < cut:
            return name


def pctile(x, xs):
    return round(100 * sum(v <= x for v in xs) / len(xs))


def readout(hist=HIST, live=False, ser=None):
    ser = ser or series(hist, live)
    rows = curve(ser)
    if not rows:
        return {"error": "no Cboe history; run with --pull"}
    d, v9, v, v3 = rows[-1]
    main, front = v / v3, v9 / v
    mains = [r[2] / r[3] for r in rows]
    fronts = [r[1] / r[2] for r in rows]
    st = state_of(main)
    run = 0  # consecutive sessions in the current state
    for m in reversed(mains):
        if state_of(m) != st:
            break
        run += 1
    back = [i for i, m in enumerate(mains) if m >= 1]
    last_back = rows[back[-1]][0] if back else None
    prev5 = mains[-6] if len(mains) > 5 else None
    shape = "inverted" if v9 > v > v3 else "upward" if v9 < v < v3 else "kinked"
    return {
        "date": d, "vix9d": v9, "vix": v, "vix3m": v3,
        "ratio_vix_vix3m": round(main, 3), "ratio_vix9d_vix": round(front, 3),
        "state": st, "tone": CAL[st], "shape": shape, "sessions_in_state": run,
        "pctile_ratio_since_2011": pctile(main, mains), "pctile_front_since_2011": pctile(front, fronts),
        "ratio_5d_change": round(main - prev5, 3) if prev5 else None,
        "last_backwardation_date": last_back,
        "backwardation_share_since_2011": round(len(back) / len(mains), 3),
        "next_week_vol": week_vol(ser, d, v9, v, v3),
        "finding": FINDING, "use": "context only; never moves a probability",
        "source": "Cboe daily index history (cdn.cboe.com), VIX9D/VIX/VIX3M closes",
    }


def line(r):
    """One plain line for a 'Today' context row."""
    w = r.get("next_week_vol") or {}
    ext = f"; model's next-week vol {w['with_curve']}% vs VIX {r['vix']}" if w else ""
    return (f"VIX curve {r['state']} ({r['tone']}): VIX9D {r['vix9d']:.2f} / VIX {r['vix']:.2f} / VIX3M {r['vix3m']:.2f}, "
            f"VIX/VIX3M {r['ratio_vix_vix3m']} ({r['pctile_ratio_since_2011']}th pct since 2011), "
            f"{r['sessions_in_state']} sessions in this state{ext}. Context only.")


def desk_docs(r, day=None):
    """Desk Daily docs: meta/vixterm (full readout) and days/<date>.vixterm (compact)."""
    meta = dict(r, updated=day or r.get("date"), line=line(r))
    w = r.get("next_week_vol") or {}
    dayv = {k: r.get(k) for k in ("date", "vix9d", "vix", "vix3m", "ratio_vix_vix3m", "ratio_vix9d_vix", "state",
                                  "tone", "shape", "sessions_in_state", "pctile_ratio_since_2011")}
    dayv["next_week_vol_model"] = w.get("with_curve")
    dayv["line"] = meta["line"]
    return {"meta_vixterm": meta, "day_vixterm": dayv}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--hist", default=str(HIST))
    ap.add_argument("--json")
    ap.add_argument("--desk", help="write {meta_vixterm, day_vixterm} for Desk Daily to this path")
    ap.add_argument("--date", help="session date for --desk (default: latest Cboe close)")
    a = ap.parse_args(argv)
    if a.pull:
        pull(a.hist)
    out = readout(a.hist, a.live)
    s = json.dumps(out, indent=1)
    if a.json:
        Path(a.json).write_text(s)
    if a.desk:
        Path(a.desk).write_text(json.dumps(desk_docs(out, a.date), indent=1))
    print(s)


if __name__ == "__main__":
    main()
