"""Desk health check: did every scheduled run happen, and did any of them fail?

The morning briefing skipped 7-25 Nov 2026 and nobody noticed for 18 days. This
script makes that impossible to miss. The close scorecard runs it every weekday
(from the copy stored in Desk Ledger method/health_script) and writes the result
to Desk Daily meta/health, which the front of the Desk Daily page shows as a
green / amber / red light.

    python3 health.py --runs <dir of ledger runs JSON> --pred <dir of ledger predictions JSON>
                      --date YYYY-MM-DD [--hub-built 2026-11-26T23:20:00Z] [--out health.json]

Inputs are the files ArtifactData saves with out_dir (one JSON per doc, either the
bare doc or {"data": doc}). Stdlib only, single file. Analysis only.
"""
import argparse, glob, json, os, re, sys
from datetime import date, datetime, timedelta, timezone

VERSION = "1.0"

# NYSE full-day closures (half days still run).
HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
    "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
    "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}

# name pattern -> (label, which day it must exist for)
#   "today": a weekday run that should have logged by the time the close runs
#   "prev":  a run that fires after the close, so check the previous trading day
EXPECTED = [
    (r"^morning briefing", "Morning briefing", "today"),
    (r"^pre-open", "Pre-open check", "today"),
    (r"^midday", "Midday run", "today"),
    (r"^close scorecard", "Close scorecard", "prev"),
    (r"^event engine", "Event engine", "prev"),
]
FAIL_WORDS = re.compile(r"\b(script failed|failed to run|failure|error|traceback|timed out|could not run|token (?:is )?missing)\b", re.I)
OK_CONTEXT = re.compile(r"\bno (?:errors?|failures?)\b|\b0 errors?\b", re.I)


def load_dir(d):
    out = []
    if not d:
        return out
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        try:
            x = json.load(open(f))
        except Exception:
            continue
        x = x.get("data", x) if isinstance(x, dict) else {}
        x.setdefault("_id", os.path.splitext(os.path.basename(f))[0])
        out.append(x)
    return out


def run_date(r):
    """The ET calendar date a runs row belongs to, from 'at' (ISO or free text) or its id."""
    for s in (str(r.get("at", "")), str(r.get("_id", ""))):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
        if not m:
            continue
        d = m.group(1)
        # an ISO time in UTC late in the evening belongs to the previous ET day
        m2 = re.search(r"\d{4}-\d{2}-\d{2}T(\d{2}):\d{2}(?::\d{2})?Z", s)
        if m2 and int(m2.group(1)) < 5:
            d = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        return d
    return None


def is_trading(d):
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def prev_trading(d):
    d = date.fromisoformat(d) - timedelta(days=1)
    while not is_trading(d):
        d -= timedelta(days=1)
    return d.isoformat()


def check(runs, preds, today, hub_built=None, now=None):
    issues, ok = [], []
    trading = is_trading(today)
    prev = prev_trading(today)
    by_day = {}
    for r in runs:
        by_day.setdefault(run_date(r), []).append(r)

    def found(pat, day):
        return [r for r in by_day.get(day, []) if re.search(pat, str(r.get("name", "")), re.I)]

    for pat, label, when in EXPECTED:
        if when == "today" and not trading:
            continue
        day = today if when == "today" else prev
        rows = found(pat, day)
        if not rows:
            issues.append({"level": "red" if label in ("Morning briefing", "Close scorecard") else "amber",
                           "what": f"{label} did not log a run for {day}"})
        else:
            ok.append(f"{label} {day}")

    # Sunday desk (checked on Mondays and after): the last Sunday should have a Monday Guess / weekly run
    t = date.fromisoformat(today)
    last_sun = (t - timedelta(days=(t.weekday() + 1) % 7 or 7)).isoformat() if t.weekday() != 6 else None
    if last_sun and (t - date.fromisoformat(last_sun)).days <= 6:
        if not [r for r in by_day.get(last_sun, []) if re.search(r"sunday|weekly|monday guess", str(r.get("name", "")), re.I)]:
            issues.append({"level": "amber", "what": f"Sunday desk did not log a run for {last_sun}"})
        else:
            ok.append(f"Sunday desk {last_sun}")

    # failures written into run summaries (a blocked news site is normal and not counted) in the last 2 trading days
    for day in {today, prev}:
        for r in by_day.get(day, []):
            s = str(r.get("summary", ""))
            m = FAIL_WORDS.search(OK_CONTEXT.sub("", s))
            if m:
                i = max(0, m.start() - 60)
                issues.append({"level": "amber", "what": f"{r.get('name', 'run')} {day} reports a problem: ...{s[i:m.end() + 60].strip()}..."})

    # calls stuck open well past their resolve date (grading pipe broken)
    stuck = []
    for p in preds:
        if p.get("status") == "open" and p.get("resolves"):
            try:
                res = date.fromisoformat(str(p["resolves"])[:10])
            except ValueError:
                continue
            lag = sum(1 for k in range(1, (t - res).days + 1) if is_trading(res + timedelta(days=k)))
            if lag >= 3:
                stuck.append(p.get("_id"))
    if stuck:
        issues.append({"level": "amber", "what": f"{len(stuck)} call(s) still open 3+ trading days after they resolved: {', '.join(sorted(stuck)[:8])}"})

    # nightly data job (GitHub Actions) freshness
    if hub_built:
        try:
            hb = datetime.fromisoformat(hub_built.replace("Z", "+00:00"))
            now = now or datetime.now(timezone.utc)
            age_h = (now - hb).total_seconds() / 3600
            if age_h > 54:
                issues.append({"level": "amber", "what": f"Nightly data job last built {hub_built} ({age_h:.0f} hours ago)"})
            else:
                ok.append("Nightly data job")
        except ValueError:
            issues.append({"level": "amber", "what": f"Nightly data job built_at unreadable: {hub_built}"})

    status = "red" if any(i["level"] == "red" for i in issues) else ("amber" if issues else "green")
    words = {"green": "All scheduled runs logged, nothing failed.",
             "amber": f"{len(issues)} thing(s) to look at.",
             "red": "A key run is missing: today's numbers may be thin or unofficial."}[status]
    return {"version": VERSION, "date": today, "trading_day": trading, "status": status, "summary": words,
            "issues": issues, "ok": ok, "checked_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--pred")
    ap.add_argument("--date", required=True)
    ap.add_argument("--hub-built")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    h = check(load_dir(a.runs), load_dir(a.pred), a.date, a.hub_built)
    js = json.dumps(h, indent=1)
    if a.out:
        open(a.out, "w").write(js)
    print(f"HEALTH {h['status'].upper()}: {h['summary']}")
    for i in h["issues"]:
        print(f" - [{i['level']}] {i['what']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
