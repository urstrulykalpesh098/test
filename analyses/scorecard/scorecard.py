"""Build weekly scorecard rows: desk vs VIX formula vs simulator vs "trend follows yesterday".

Usage: python3 scorecard.py <dir of ledger prediction JSON files> <out.json> [--book meta_book.json] [--rows rows.json]
--book: Desk Daily meta/book (raw ArtifactData JSON) adds paper book vs SPY by week.
--rows: also write the flat {rows, meta} file the Desk Scorecard page loads.
Writes {"weeks": [...], "running": {...}} ready to store as the scorecard page's
weeks/{monday} docs and meta/running. Weeks are keyed by the Monday of the week a
call RESOLVES in (calls graded early count in the current week). Nothing here is invented: every number is recomputed from the
graded ledger calls. Not investment advice.
"""
import json, statistics as st, sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import baselines as B

def load_formula():
    """Reuse base_prob from the desk's baseline backtest without running its main block."""
    src = (HERE.parent / "desk" / "backtest_baseline.py").read_text().split("rows=[]")[0]
    g = {}; exec(src, g)
    return g["base_prob"]

def graded(dirpath):
    out = []
    for f in sorted(Path(dirpath).glob("*.json")):
        d = json.load(open(f)); x = d.get("data", d)
        if x.get("status") in ("hit", "miss") and isinstance(x.get("prob"), (int, float)):
            out.append((f.stem, x))
    return out

def br(xs):
    return round(st.mean((p - y) ** 2 for p, y in xs), 3) if xs else None

def block(calls, base_prob, follow_rows):
    allc = [(float(x["prob"]), int(x["status"] == "hit")) for _, x in calls]
    m_desk, m_base, m_sim, sim_pairs = [], [], [], []
    for pid, x in calls:
        y = int(x["status"] == "hit")
        b = x.get("prob_base")
        if not isinstance(b, (int, float)):
            pre = ("pre-open" in x.get("source", "").lower()) or pid.startswith(("pre", "mg", "mon"))
            b = base_prob(x["claim"], x["made"], x["resolves"], pre)
        if b is not None:
            m_desk.append((float(x["prob"]), y)); m_base.append((b, y))
        s = x.get("prob_sim")
        if isinstance(s, (int, float)):
            sim_pairs.append((float(x["prob"]), s, y))
    fr = follow_rows
    return {
        "n": len(allc),
        "hits": sum(y for _, y in allc),
        "desk_brier_all": br(allc),
        "said_avg": round(st.mean(p for p, _ in allc), 3) if allc else None,
        "n_matched": len(m_desk),
        "desk_brier": br(m_desk),
        "formula_brier": br(m_base),
        "n_sim": len(sim_pairs),
        "desk_brier_simset": br([(p, y) for p, _, y in sim_pairs]),
        "sim_brier": br([(s, y) for _, s, y in sim_pairs]),
        "updown": {
            "n": len(fr),
            "days": len({r["resolves"] for r in fr}),
            "ups": sum(r["y"] for r in fr),
            "desk_brier": br([(r["desk"], r["y"]) for r in fr]),
            "follow_brier": br([(r["follow"], r["y"]) for r in fr]),
            "formula_brier": br([(r["formula"], r["y"]) for r in fr]),
            "desk_right": B.hits(fr, "desk")[0], "desk_called": B.hits(fr, "desk")[1],
            "follow_right": B.hits(fr, "follow")[0], "follow_called": B.hits(fr, "follow")[1],
        },
    }

def book_by_week(book):
    """Week-end paper-book equity and SPY from meta/book's curve; returns vs the book's start."""
    if not book:
        return {}
    b = book.get("data", book)
    curve = sorted(b.get("curve") or [], key=lambda c: c["date"])
    if not curve:
        return {}
    e0, s0 = float(b.get("start") or curve[0]["equity"]), float(curve[0]["spy"])
    out = {}
    for c in curve:
        out[B.monday(c["date"])] = {
            "book_equity": round(float(c["equity"]), 2),
            "book_ret_pct": round((float(c["equity"]) / e0 - 1) * 100, 2),
            "spy_ret_pct": round((float(c["spy"]) / s0 - 1) * 100, 2),
            "book_points": len([x for x in curve if x["date"] <= c["date"]]),
        }
    return out

FLAT = ["week_of", "n", "hits", "desk_brier_all", "said_avg", "n_matched", "desk_brier", "formula_brier",
        "n_sim", "desk_brier_simset", "sim_brier"]

def flat(w):
    r = {k: w.get(k) for k in FLAT}
    for k, v in w["updown"].items():
        r["ud_" + k] = v
    for k in ("book_equity", "book_ret_pct", "spy_ret_pct", "book_points"):
        r[k] = w.get(k)
    return r

def build(dirpath, book=None):
    base_prob = load_formula()
    calls = graded(dirpath)
    fr = B.rows_from(dirpath, B.load_closes())
    byweek = {}
    today = date.today().isoformat()
    for pid, x in calls:
        # a multi-week call graded early counts in the week it was graded (no later than today)
        byweek.setdefault(B.monday(min(x["resolves"], today)), []).append((pid, x))
    weeks = []
    for w in sorted(byweek):
        weeks.append({"week_of": w, **block(byweek[w], base_prob, [r for r in fr if r["week"] == w])})
    bw = book_by_week(book)
    for w in weeks:
        w.update(bw.get(w["week_of"], {}))
    running = {"updated": date.today().isoformat(), "lean": B.LEAN, **block(calls, base_prob, fr)}
    if bw:
        running.update(bw[max(bw)])
    return {"weeks": weeks, "running": running}

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    a = sys.argv
    book = json.load(open(a[a.index("--book") + 1])) if "--book" in a else None
    out = build(a[1], book)
    json.dump(out, open(a[2], "w"), indent=1)
    if "--rows" in a:
        rows = [flat(w) for w in out["weeks"]]
        allrow = flat({**out["running"], "week_of": "All weeks"})
        code = [{"label": n, "value": (HERE / n).read_text(), "type": "code", "lang": "python"}
                for n in ("scorecard.py", "baselines.py")]
        json.dump({"rows": rows + [allrow], "meta": code + [
            {"label": "Input", "value": "Desk Ledger predictions (graded hit/miss), Desk Daily meta/book, S&P closes in analyses/data and analyses/desk/backtest_baseline.py"},
            {"label": "Updated", "value": out["running"]["updated"]}]},
            open(a[a.index("--rows") + 1], "w"), indent=0)
    r = out["running"]
    print("running: n", r["n"], "desk all", r["desk_brier_all"], "| matched", r["n_matched"],
          "desk", r["desk_brier"], "formula", r["formula_brier"], "| sim n", r["n_sim"])
    print("up/down:", r["updown"])
    for w in out["weeks"]:
        print(w["week_of"], w["n"], w["desk_brier_all"], w["desk_brier"], w["formula_brier"], w["updown"]["desk_brier"], w["updown"]["follow_brier"])
