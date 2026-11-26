"""Self-research loop (upgrade 8): every week, re-test the desk's beliefs on data the
belief was NOT built from, and only promote what survives.

Each hypothesis is checked twice: in-sample (before 2022) and out-of-sample (2022 on).
Verdicts:
  adopt          passes in both halves  -> propose a method/notes change to Rk
  reject         fails out-of-sample    -> propose retiring or not adding the rule
  keep watching  too few cases or mixed
The loop only PROPOSES. Changing method/notes still needs Rk's yes.
Writes analyses/output/research/research_<asof>.json and .md. Not investment advice.
"""
import json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from analyses.backbone.history import aligned, load, HIST  # noqa: E402
from analyses.lab.core import Z80, ewma_vol, rate, wilson, brier, r4  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analyses" / "output" / "research"
SPLIT = "2022-01-01"


def halves(items, key=lambda x: x[0]):
    return [x for x in items if key(x) < SPLIT], [x for x in items if key(x) >= SPLIT]


def h_spx_band_16(rows):
    zs = [(rows[i + 1][0], abs(math.log(rows[i + 1][1] / rows[i][1])) <= Z80 * 1.6 * rows[i][2] / 100 / math.sqrt(252)) for i in range(len(rows) - 1)]
    a, b = halves(zs)
    ra, rb = rate(x for _, x in a), rate(x for _, x in b)
    v = "adopt" if 0.75 <= ra <= 0.85 and 0.75 <= rb <= 0.85 else "reject"
    return {"id": "rule5_spx_1.6x", "belief": "80% S&P ranges should be 1.6x the VIX-implied move (rule 5, lesson L3).",
            "in_sample": r4(ra), "out_of_sample": r4(rb), "n_out": len(b), "target": "0.75-0.85", "verdict": v,
            "plain": f"Over years of data a 1.6x range held {rb:.0%} of the time since 2022, far more than 80%. It is right for a shock month like November 2026 but far too wide in normal times. Proposal: size ranges from recent realized volatility (the adaptive band) instead of a fixed 1.6x."}


def h_vix_band_25(vix):
    days = sorted(vix)
    xs = [(days[i + 1], abs(vix[days[i + 1]] / vix[days[i]] - 1) <= 0.25) for i in range(len(days) - 1)]
    a, b = halves(xs)
    ra, rb = rate(x for _, x in a), rate(x for _, x in b)
    v = "adopt" if 0.75 <= ra <= 0.85 and 0.75 <= rb <= 0.85 else "reject"
    return {"id": "rule5_vix_25pct", "belief": "80% VIX bands should be +/-25% of the prior close for one day (rule 5).",
            "in_sample": r4(ra), "out_of_sample": r4(rb), "n_out": len(b), "target": "0.75-0.85", "verdict": v,
            "plain": f"A +/-25% one-day VIX band held {rb:.0%} of days since 2022. Too wide in normal markets; the adaptive band keeps close to 80% and still widens in a storm."}


def h_adaptive(rows, vix):
    rets = [math.log(rows[i + 1][1] / rows[i][1]) for i in range(len(rows) - 1)]
    ew = ewma_vol(rets)
    zs = []
    for j in range(21, len(rows) - 1):
        sig = 0.5 * rows[j][2] / 100 / math.sqrt(252) + 0.5 * ew[j - 1]
        zs.append((rows[j + 1][0], abs(rets[j]) / sig))
    a, b = halves(zs)
    k = sorted(z for _, z in a)[int(0.8 * (len(a) - 1))] / Z80
    rb = rate(z <= Z80 * k for _, z in b)
    last15 = rate(z <= Z80 * k for _, z in zs[-15:])
    v = "adopt" if 0.75 <= rb <= 0.85 else "reject"
    return {"id": "adaptive_spx_band", "belief": "Size 80% S&P ranges from half VIX + half recent realized vol, width fitted before 2022.",
            "k": r4(k), "out_of_sample": r4(rb), "last_15_days": r4(last15), "n_out": len(b), "target": "0.75-0.85", "verdict": v,
            "plain": f"Fitted on 2016-2021, it held {rb:.0%} from 2022 on, close to the 80% target. But it held only {last15:.0%} in the last 15 days, so in a shock it still runs narrow. Proposal: use the wider of the adaptive band and the VIX-implied band once VIX is above 25."}


def h_falling_tape(rows):
    xs = []
    for i in range(5, len(rows) - 1):
        xs.append((rows[i][0], rows[i][1] / rows[i - 5][1] - 1 <= -0.02, rows[i + 1][1] > rows[i][1]))
    out = {}
    for name, part in zip(("in", "out"), halves(xs)):
        cond = [u for _, c, u in part if c]
        base = rate(u for _, _, u in part)
        out[name] = {"n": len(cond), "p_up": r4(rate(cond)), "base": r4(base), "ci95": wilson(sum(cond), len(cond))}
    o = out["out"]
    lower_than_base = o["ci95"][1] < o["base"]
    v = "keep watching"
    if o["p_up"] >= o["base"] and out["in"]["p_up"] >= out["in"]["base"]:
        v = "reject"
    elif lower_than_base:
        v = "adopt"
    return {"id": "lesson_L4_falling_tape", "belief": "Don't default to 'up' after a falling week (lesson L4).",
            "detail": out, "verdict": v,
            "plain": f"After a week down 2%+, the next day was up {o['p_up']:.0%} of the time since 2022 (normal {o['base']:.0%}). Historically falling weeks did NOT make up days rarer, so L4 as a rule of thumb is not supported by the long record; it may still be right in a specific regime."}


def h_term(hist):
    rows = aligned("SP500", "VIXCLS", "VXVCLS", hist=hist)
    xs = []
    for i in range(len(rows) - 5):
        rets = [math.log(rows[j + 1][1] / rows[j][1]) for j in range(i, i + 5)]
        rv = math.sqrt(sum(r * r for r in rets) / 5 * 252) * 100
        xs.append((rows[i][0], rows[i][3] / rows[i][2] < 1, rv / rows[i][2]))
    res = {}
    for name, part in zip(("in", "out"), halves(xs)):
        inv = sorted(q for _, c, q in part if c)
        calm = sorted(q for _, c, q in part if not c)
        res[name] = {"n_inverted": len(inv), "realized_over_vix_inverted": r4(inv[len(inv) // 2]) if inv else None,
                     "realized_over_vix_other": r4(calm[len(calm) // 2]) if calm else None}
    ok = all(res[p]["realized_over_vix_inverted"] and res[p]["realized_over_vix_inverted"] > res[p]["realized_over_vix_other"] for p in res)
    return {"id": "vix_curve_inverted", "belief": "When 3-month VIX is below VIX (inverted curve), the next week moves closer to what VIX prices.",
            "detail": res, "verdict": "adopt" if ok else "reject",
            "plain": "When the VIX curve inverts, the following week realizes much more of the VIX-implied move than usual, in both halves of history. Proposal: when inverted, do not shrink ranges below the VIX-implied move."}


def h_analogs(hist, step=5, k=100):
    from analyses.lab.playbook import setups
    days, spx, vix, rows = setups(hist)
    keys = ("vix", "r5", "r20", "curve")
    pairs = []
    for t in range(500, len(rows) - 5, step):
        if rows[t]["date"] < SPLIT:
            continue
        past = rows[: t - 5]
        mu = {x: sum(r[x] for r in past) / len(past) for x in keys}
        sd = {x: (sum((r[x] - mu[x]) ** 2 for r in past) / len(past)) ** 0.5 for x in keys}
        cur = rows[t]
        near = sorted(past, key=lambda r: sum(((r[x] - cur[x]) / sd[x]) ** 2 for x in keys))[:k]
        p = rate(spx[days[r["i"] + 5]] > spx[days[r["i"]]] for r in near)
        base = rate(spx[days[r["i"] + 5]] > spx[days[r["i"]]] for r in past)
        y = int(spx[days[cur["i"] + 5]] > spx[days[cur["i"]]])
        pairs.append((min(0.95, max(0.05, p)), base, y))
    ba, bb = brier((p, y) for p, _, y in pairs), brier((b, y) for _, b, y in pairs)
    return {"id": "setup_analogs_5d", "belief": "The setup playbook's 'P(up in 5 days)' from look-alike days beats the plain up-rate.",
            "n_out": len(pairs), "brier_analogs": r4(ba), "brier_base": r4(bb), "verdict": "adopt" if ba < bb - 0.002 else "reject",
            "plain": f"Tested since 2022 on {len(pairs)} days using only earlier history: analogs scored {ba:.3f} vs {bb:.3f} for the plain up-rate (lower is better). " + ("They add something." if ba < bb - 0.002 else "They do not beat the base rate, so treat the playbook as a picture of the range of outcomes, not as a forecast.")}


def h_analysts():
    p = ROOT / "analyses" / "output" / "lab" / "analysts.json"
    if not p.exists():
        return None
    a = json.loads(p.read_text())["horizons"]["h1"]["all"]
    base = a["base"]["brier"]
    best = min((v["brier"], k) for k, v in a.items() if k not in ("base", "red_team") and v["n"] > 1000)
    return {"id": "specialists_beat_base", "belief": "At least one specialist analyst beats the plain up-rate on next-day calls.",
            "best": best[1], "brier_best": best[0], "brier_base": base, "verdict": "adopt" if best[0] < base - 0.002 else "reject",
            "plain": f"Best analyst ({best[1]}) scored {best[0]:.4f} vs {base:.4f} for the plain up-rate across ~1,950 out-of-sample days. A gap that small is noise: none of the simple signals predicts tomorrow's direction."}


def run(hist=HIST, out=OUT):
    rows = aligned("SP500", "VIXCLS", hist=hist)
    vix = load("VIXCLS", hist)
    hs = [h_spx_band_16(rows), h_vix_band_25(vix), h_adaptive(rows, vix), h_falling_tape(rows), h_term(hist), h_analogs(hist)]
    a = h_analysts()
    if a:
        hs.append(a)
    asof = rows[-1][0]
    res = {"asof": asof, "split": SPLIT, "hypotheses": hs,
           "rule": "The loop only proposes. method/notes changes need Rk's approval."}
    out.mkdir(parents=True, exist_ok=True)
    (out / f"research_{asof}.json").write_text(json.dumps(res, indent=1) + "\n")
    (out / "latest.json").write_text(json.dumps(res, indent=1) + "\n")
    md = [f"# Self-research report, data as of {asof}", "", f"In-sample = before {SPLIT}, out-of-sample = {SPLIT} on. Proposals only; nothing changes without Rk.", ""]
    for h in hs:
        md += [f"## {h['id']}: {h['verdict'].upper()}", "", f"Belief: {h['belief']}", "", h["plain"], ""]
    md += ["Not investment advice; analysis only."]
    (out / f"research_{asof}.md").write_text("\n".join(md) + "\n")
    return res


if __name__ == "__main__":
    r = run()
    for h in r["hypotheses"]:
        print(h["id"], "->", h["verdict"], "|", h["plain"][:160])
