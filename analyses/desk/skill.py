"""Skill or luck meter: is the desk's edge over its no-judgment baselines real, or noise?

For every graded S&P 500 / VIX call it re-grades the outcome on official FRED closes
(SP500, VIXCLS; method/notes rule 8) and scores the desk's probability against a
fixed baseline that was knowable when the call was made:

  updown : "S&P 500 closes up on D"   -> base rate 0.54 (rule 1). Also shown: formula 0.50.
  level  : "closes above/below K on D" -> VIX formula: zero drift, daily sigma = VIX/100/sqrt(252)
           ("200-day average" calls use the true 200-day line from FRED, not the call's estimate)
  range  : "close lands inside A-B"    -> same VIX formula
  vix    : "VIX closes between/above/below" -> VIX's own wobble: zero drift, log sigma = 20-day
           realised sd of VIX log changes (rule 5 v5's VIX sigma)

Calls on other assets (single stocks, ETFs, data prints) and path-dependent calls
("any day", "within 21 sessions") are left out: no official close or no clean baseline.

Edge = baseline Brier minus desk Brier (positive = desk better). Several calls resolve on
the same day and move together, so all uncertainty is by resolve day:
  - bootstrap: resample resolve days with replacement (10,000 draws) -> 95% interval
  - permutation: flip desk/baseline labels for whole days at random -> p-value
  - calls needed: how many more graded calls before a 95% interval would clear zero
    80% of the time, if the edge stays its current size (and for a 0.01 edge).

    python3 skill.py --pred <ledger predictions dir> [--history <dir with SP500.csv, VIXCLS.csv>]
                     [--out skill.json] [--desk meta_skill.json]

Without --history it pulls FRED directly. Stdlib only, single file (copy in the Desk Ledger
as method/skill_script). Analysis only, not investment advice.
"""
import argparse, csv, io, json, math, random, re, statistics as st, sys, time, urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

VERSION = "1.0"
UA = "curl/8.5.0"  # FRED stalls on browser-like and unknown agents
BASE_UP = 0.54
# graded calls a trading day under rule 6: one up/down, one range, one VIX band, about one extra
PER_DAY = {"all": 4, "updown": 1, "updown_coin": 1, "level": 1, "range": 1, "vix": 1}
DRAWS = 10000
TYPES = ("updown", "level", "range", "vix")
PLAIN = {"updown": "Up/down calls", "level": "S&P above/below a level",
         "range": "S&P 80% ranges", "vix": "VIX calls", "all": "All S&P and VIX calls"}
BASE_NAME = {"updown": "54% base rate", "level": "VIX formula", "range": "VIX formula",
             "vix": "VIX's own recent wobble", "all": "baselines"}

N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
num = lambda s: float(s.replace(",", ""))


# ---------- data ----------
def parse_csv(text):
    out = {}
    r = csv.reader(io.StringIO(text))
    next(r, None)
    for line in r:
        if len(line) < 2:
            continue
        v = line[1].strip()
        if not v or v == ".":
            continue
        try:
            datetime.strptime(line[0].strip(), "%Y-%m-%d")
            out[line[0].strip()] = float(v)
        except ValueError:
            pass
    return out


def fred(sid, tries=3):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return parse_csv(resp.read().decode("utf-8", "replace"))
        except Exception as e:  # network
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{sid}: {last}")


def load_closes(history=None):
    if history:
        h = Path(history)
        return parse_csv((h / "SP500.csv").read_text()), parse_csv((h / "VIXCLS.csv").read_text())
    return fred("SP500"), fred("VIXCLS")


def load_preds(d):
    out = {}
    for f in sorted(Path(d).glob("*.json")):
        x = json.load(open(f))
        out[f.stem] = x.get("data", x)
    return out


# ---------- classify ----------
PATH_DEP = re.compile(r"any day|at least one|within \d+|through|high-to-low|intraday|range is", re.I)
UPDOWN = re.compile(r"^S&P 500 closes up on", re.I)
NUMS = r"([\d,]{4,6}(?:\.\d+)?)"


def classify(claim):
    """-> (type, spec) or None. spec holds thresholds."""
    c = claim.replace("–", "-").replace("—", "-")
    if PATH_DEP.search(c):
        return None
    if c.startswith("VIX "):
        m = re.search(r"between\s+([\d.]+)\s+and\s+([\d.]+)", c)
        if m:
            return "vix", {"lo": float(m.group(1)), "hi": float(m.group(2))}
        m = re.search(r"(above|below|under|over)\s+([\d.]+)", c)
        if m:
            return "vix", {"side": "above" if m.group(1) in ("above", "over") else "below", "k": float(m.group(2))}
        return None
    if not c.startswith("S&P 500"):
        return None
    if UPDOWN.search(c):
        return "updown", {}
    m = re.search(r"inside\s+" + NUMS + r"\s*-\s*" + NUMS, c)
    if m:
        a, b = sorted([num(m.group(1)), num(m.group(2))])
        return "range", {"lo": a, "hi": b}
    m = re.search(r"\b(above|below|higher than|lower than|under|over)\b(.*)", c)
    if m:
        k = re.search(r"(?<![\d,.])" + NUMS, m.group(2))
        if k:
            return "level", {"side": "above" if m.group(1) in ("above", "higher than", "over") else "below",
                             "k": num(k.group(1)), "ma200": "200-day" in c}
    return None


def is_pre(pid, x):
    """True when the call was made before that day's close was known."""
    src = (x.get("source") or "").lower()
    return (x.get("made") == x.get("resolves") or pid.startswith(("pre", "mb"))
            or "pre-open" in src or "morning briefing" in src)


# ---------- grade + baseline ----------
def grade(pid, x, sp, vix):
    """-> row dict, or (None, reason)."""
    cl = classify(x.get("claim", ""))
    if not cl:
        return None, "not an S&P/VIX close call"
    typ, spec = cl
    R, made = x.get("resolves", "")[:10], x.get("made", "")[:10]
    series = vix if typ == "vix" else sp
    if R not in series:
        return None, "no official close yet"
    ds = sorted(series)
    prior = [d for d in ds if (d < made if is_pre(pid, x) else d <= made) and d < R]
    if not prior:
        return None, "no prior close"
    d0 = prior[-1]
    h = len([d for d in ds if d0 < d <= R])
    if h < 1:
        return None, "no session"
    close = series[R]
    if typ == "level" and spec.get("ma200"):
        last = [d for d in ds if d <= R][-200:]
        if len(last) < 200:
            return None, "short S&P history"
        spec = dict(spec, k=sum(sp[d] for d in last) / 200)  # the real 200-day line on FRED
    if typ == "updown":
        prev = [d for d in ds if d < R][-1]
        y = int(close > series[prev])
        base, alt = BASE_UP, 0.5
    else:
        if typ == "vix":
            i = ds.index(d0)
            win = ds[max(0, i - 20):i + 1]
            lr = [math.log(vix[b] / vix[a]) for a, b in zip(win, win[1:])]
            if len(lr) < 10:
                return None, "short VIX history"
            s, C = st.pstdev(lr) * math.sqrt(h), vix[d0]
        else:
            if d0 not in vix:
                return None, "no VIX on base day"
            s, C = vix[d0] / 100 / math.sqrt(252) * math.sqrt(h), sp[d0]
        if "lo" in spec:
            y = int(spec["lo"] <= close <= spec["hi"])
            base = N(math.log(spec["hi"] / C) / s) - N(math.log(spec["lo"] / C) / s)
        else:
            up = N(math.log(C / spec["k"]) / s)
            above = close > spec["k"]
            y = int(above if spec["side"] == "above" else not above)
            base = up if spec["side"] == "above" else 1 - up
        alt = None
    p = float(x["prob"])
    led = x.get("status")
    return {"id": pid, "type": typ, "resolves": R, "prob": p, "base": round(base, 4),
            "alt": alt, "y": y, "ledger": led, "agrees": (led == "hit") == bool(y)}, None


def rows(preds, sp, vix):
    out, skipped = [], {}
    for pid, x in sorted(preds.items()):
        if x.get("status") not in ("hit", "miss") or not isinstance(x.get("prob"), (int, float)):
            continue
        r, why = grade(pid, x, sp, vix)
        if r:
            out.append(r)
        else:
            skipped[why] = skipped.get(why, 0) + 1
    return out, skipped


# ---------- stats ----------
def by_day(rs, key="base"):
    g = {}
    for r in rs:
        d = (r[key] - r["y"]) ** 2 - (r["prob"] - r["y"]) ** 2  # >0: desk better
        g.setdefault(r["resolves"], []).append(d)
    return [(sum(v), len(v)) for _, v in sorted(g.items())]


def test(rs, key="base", seed=7):
    if not rs:
        return None
    days = by_day(rs, key)
    n = sum(k for _, k in days)
    edge = sum(s for s, _ in days) / n
    rng = random.Random(seed)
    boots, flips = [], 0
    for _ in range(DRAWS):
        pick = [days[rng.randrange(len(days))] for _ in days]
        boots.append(sum(s for s, _ in pick) / sum(k for _, k in pick))
        perm = sum(s if rng.random() < 0.5 else -s for s, _ in days) / n
        flips += abs(perm) >= abs(edge) - 1e-12
    boots.sort()
    lo, hi = boots[int(0.025 * DRAWS)], boots[int(0.975 * DRAWS) - 1]
    se = st.pstdev(boots)
    share = sum(b > 0 for b in boots) / DRAWS
    need = lambda e: None if not e or se == 0 else max(0, math.ceil(n * (2.8 * se / abs(e)) ** 2) - n)
    db = st.mean((r["prob"] - r["y"]) ** 2 for r in rs)
    bb = st.mean((r[key] - r["y"]) ** 2 for r in rs)
    return {"n": n, "days": len(days), "desk_brier": round(db, 4), "base_brier": round(bb, 4),
            "edge": round(edge, 4), "ci95": [round(lo, 4), round(hi, 4)], "se": round(se, 4),
            "p_value": round(flips / DRAWS, 3), "share_desk_ahead": round(share, 3),
            "more_calls_needed": need(edge), "more_calls_for_0.01": need(0.01)}


def verdict(t, typ="all"):
    if not t:
        return "none", "No graded calls yet."
    lo, hi = t["ci95"]
    if lo > 0:
        return "skill", "Looks like real skill: the desk beats its baseline even on the unlucky end of the range."
    if hi < 0:
        return "worse", "The desk is reliably worse than its baseline here. That is not bad luck; the judgment is costing points."
    m = t["more_calls_needed"]
    if m is None or m > 5000:
        return "noise", "Can't tell yet, and the edge is so close to zero that more calls may never settle it. For now this is indistinguishable from luck."
    return "early", f"Too early to tell: need about {m} more graded calls (~{math.ceil(m / PER_DAY[typ])} trading days) if the edge holds."


def headline(t, typ):
    if not t:
        return ""
    e = t["edge"]
    side = "ahead of" if e > 0 else "behind"
    return (f"{PLAIN[typ]}: desk {t['desk_brier']:.3f} vs {BASE_NAME[typ]} {t['base_brier']:.3f} "
            f"({abs(e):.3f} {side}, n={t['n']} on {t['days']} days)")


def build(preds, sp, vix, today=None):
    rs, skipped = rows(preds, sp, vix)
    res = {"version": VERSION, "built": today or date.today().isoformat(),
           "graded_on": f"FRED SP500 to {max(sp)}, VIXCLS to {max(vix)}",
           "n_used": len(rs), "skipped": skipped,
           "ledger_disagrees": [r["id"] for r in rs if not r["agrees"]], "types": {}}
    for typ in ("all",) + TYPES:
        sub = rs if typ == "all" else [r for r in rs if r["type"] == typ]
        t = test(sub)
        v, words = verdict(t, typ)
        res["types"][typ] = {"label": PLAIN[typ], "baseline": BASE_NAME[typ], "verdict": v,
                             "words": words, "line": headline(t, typ), **(t or {"n": 0})}
    ud = [r for r in rs if r["type"] == "updown"]
    t50 = test(ud, key="alt")
    if t50:
        res["updown_vs_coin"] = {"baseline": "VIX formula (50%)", **t50, "verdict": verdict(t50, "updown_coin")[0]}
    a = res["types"]["all"]
    res["today_line"] = (f"Skill or luck: {a['words'].split(':')[0].rstrip('.')}." if a["verdict"] != "early"
                         else f"Skill or luck: too early to tell, need ~{a['more_calls_needed']} more graded calls "
                              f"(about {math.ceil(a['more_calls_needed'] / PER_DAY['all'])} trading days).")
    if a.get("n"):
        res["today_line"] += (f" Desk {a['desk_brier']:.3f} vs baselines {a['base_brier']:.3f} on {a['n']} calls; "
                              f"ahead in {round(100 * a['share_desk_ahead'])}% of reshuffles.")
    res["rows"] = rs
    return res


def table(res):
    """Flat rows, one per call type, for the Scorecard page."""
    out = []
    items = [(k, res["types"][k]) for k in ("all",) + TYPES]
    if "updown_vs_coin" in res:
        items.insert(2, ("updown_coin", dict(res["updown_vs_coin"], label="Up/down calls vs a 50% coin",
                                             words=verdict(res["updown_vs_coin"], "updown_coin")[1])))
    for k, t in items:
        if not t.get("n"):
            continue
        r3 = lambda v: round(v, 3)
        out.append({"type": k, "label": t["label"], "baseline": t["baseline"], "n": t["n"], "days": t["days"],
                    "desk_brier": r3(t["desk_brier"]), "base_brier": r3(t["base_brier"]), "edge": r3(t["edge"]),
                    "ci_lo": r3(t["ci95"][0]), "ci_hi": r3(t["ci95"][1]), "p_value": round(t["p_value"], 2),
                    "share_ahead_pct": round(100 * t["share_desk_ahead"]), "more_needed": t["more_calls_needed"],
                    "more_for_001": t["more_calls_for_0.01"], "verdict": t["verdict"], "words": t["words"]})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--history")
    ap.add_argument("--out")
    ap.add_argument("--desk", help="write {meta_skill} for Desk Daily meta/skill")
    ap.add_argument("--rows", help="write {rows, meta} for the Desk Scorecard 'skill' dataset")
    a = ap.parse_args(argv)
    sp, vix = load_closes(a.history)
    res = build(load_preds(a.pred), sp, vix)
    if a.out:
        json.dump(res, open(a.out, "w"), indent=1)
    if a.desk:
        slim = {k: v for k, v in res.items() if k != "rows"}
        json.dump({"meta_skill": slim}, open(a.desk, "w"), indent=1)
    if a.rows:
        json.dump({"rows": table(res), "meta": [
            {"label": "skill.py", "value": Path(__file__).read_text(), "type": "code", "lang": "python"},
            {"label": "Input", "value": "Desk Ledger predictions (graded hit/miss), re-graded on " + res["graded_on"]},
            {"label": "Left out", "value": ", ".join(f"{v} {k}" for k, v in res["skipped"].items())},
            {"label": "Built", "value": res["built"]}]}, open(a.rows, "w"), indent=0)
    print(res["graded_on"], "| used", res["n_used"], "| skipped", res["skipped"])
    if res["ledger_disagrees"]:
        print("FRED disagrees with ledger grade:", ", ".join(res["ledger_disagrees"]))
    for typ in ("all",) + TYPES:
        t = res["types"][typ]
        if t.get("n"):
            print(f"{typ:<7} n={t['n']:<3} d={t['days']:<3} desk {t['desk_brier']:.3f} base {t['base_brier']:.3f} "
                  f"edge {t['edge']:+.3f} CI [{t['ci95'][0]:+.3f},{t['ci95'][1]:+.3f}] p={t['p_value']} "
                  f"ahead {t['share_desk_ahead']:.0%} need {t['more_calls_needed']} | {t['verdict']}")
    if "updown_vs_coin" in res:
        t = res["updown_vs_coin"]
        print(f"updown vs 50%: edge {t['edge']:+.3f} CI {t['ci95']} need {t['more_calls_needed']}")
    print(res["today_line"])


if __name__ == "__main__":
    main()
