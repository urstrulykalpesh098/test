"""Tests for the data backbone and the lab (stdlib unittest, no network)."""
import json, math, random, tempfile, unittest
from pathlib import Path

from analyses.backbone import pull
from analyses.backbone.history import load, aligned, asof
from analyses.lab import core, lab, multiasset, research


def synth(dirpath, n=1600, seed=7):
    """Write fake SP500/VIX/VXV/... history files with business-day dates."""
    import datetime as dt
    rnd = random.Random(seed)
    d = dt.date(2016, 1, 4)
    days = []
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += dt.timedelta(days=1)
    series = {k: [] for k in ("SP500", "VIXCLS", "VXVCLS", "DGS10", "DGS2", "BAMLH0A0HYM2", "DTWEXBGS",
                              "NASDAQCOM", "DJIA", "DCOILWTICO", "DEXCAUS", "DFEDTARU")}
    p, v = 2000.0, 18.0
    for i, day in enumerate(days):
        v = max(9, v * math.exp(rnd.gauss(0, 0.06)) * (18 / v) ** 0.05)
        p *= math.exp(rnd.gauss(0.0003, v / 100 / math.sqrt(252)))
        vals = {"SP500": p, "VIXCLS": v, "VXVCLS": v * 1.08, "DGS10": 2 + i * 0.0005, "DGS2": 1.5 + rnd.random() * 0.01,
                "BAMLH0A0HYM2": 3 + rnd.random(), "DTWEXBGS": 100 + rnd.random(), "NASDAQCOM": p * 3, "DJIA": p * 9,
                "DCOILWTICO": 60 + rnd.random(), "DEXCAUS": 1.3 + rnd.random() * 0.01, "DFEDTARU": 1.0 if i < 800 else 1.25}
        for k, x in vals.items():
            series[k].append((day, x))
    dirpath.mkdir(parents=True, exist_ok=True)
    for k, rows in series.items():
        pull.write_csv(dirpath / f"{k}.csv", rows)
    return days


class Backbone(unittest.TestCase):
    def test_parse_skips_missing(self):
        rows = pull.parse_fred_csv("observation_date,SP500\n2026-01-02,100.5\n2026-01-05,.\n2026-01-06,101\n")
        self.assertEqual(rows, [("2026-01-02", 100.5), ("2026-01-06", 101.0)])

    def test_merge_keeps_old_and_takes_revisions(self):
        self.assertEqual(pull.merge([("a", 1.0), ("b", 2.0)], [("b", 2.5), ("c", 3.0)]), [("a", 1.0), ("b", 2.5), ("c", 3.0)])

    def test_failed_fetch_keeps_file_and_marks_stale(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t)
            pull.run({"SP500"}, out, fetcher=lambda s: [("2026-01-02", 1.0)])
            def boom(s):
                raise RuntimeError("down")
            pull.run({"SP500"}, out, fetcher=boom)
            m = json.loads((out / "manifest.json").read_text())
            self.assertEqual(m["SP500"]["status"], "stale")
            self.assertEqual(load("SP500", out), {"2026-01-02": 1.0})

    def test_asof(self):
        s = {"2026-01-02": 1, "2026-01-09": 2}
        self.assertEqual(asof(s, "2026-01-05"), 1)
        self.assertIsNone(asof(s, "2026-01-01"))


class Lab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.hist = Path(cls.tmp.name) / "h"
        synth(cls.hist)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_core(self):
        self.assertAlmostEqual(core.ncdf(core.Z80), 0.9, places=6)
        a, b = core.fit_logit([-1, -1, 1, 1, 1], [0, 0, 1, 1, 0])
        self.assertGreater(b, 0)
        self.assertEqual(core.brier([(1, 1), (0, 1)]), 0.5)

    def test_bands_wider_hit_more(self):
        rows = aligned("SP500", "VIXCLS", hist=self.hist)
        r = lab.spx_bands(rows)["h1"]["by_k"]
        self.assertLessEqual(r["1.0"]["hit"], r["1.6"]["hit"])
        # synthetic returns are drawn at exactly VIX vol, so k=1 should be near 80%
        self.assertAlmostEqual(r["1.0"]["hit"], 0.8, delta=0.05)

    def test_lab_run_writes(self):
        out = Path(self.tmp.name) / "o"
        res = lab.run(self.hist, out)
        self.assertTrue((out / "lab_results.json").exists())
        self.assertIn("adaptive_bands", res)

    def test_multiasset_grades_next_value(self):
        calls = Path(self.tmp.name) / "calls.jsonl"
        out = Path(self.tmp.name) / "o2"
        r = multiasset.run(self.hist, calls, out, made_at="t")
        self.assertEqual(len(r["today"]), len(multiasset.ASSETS))
        # pretend the calls were made one day earlier, then grade
        cs = multiasset.read_calls(calls)
        days = sorted(load("SP500", self.hist))
        for c in cs:
            c["asof"] = days[-2]; c["value0"] = load(c["asset"], self.hist)[days[-2]]
        cs = multiasset.grade(cs, self.hist)
        self.assertTrue(all(c["status"] == "graded" for c in cs))
        self.assertTrue(all(c["up"] in (0, 1) and c["in_band"] in (0, 1) for c in cs))

    def test_research_verdicts(self):
        out = Path(self.tmp.name) / "r"
        res = research.run(self.hist, out)
        self.assertTrue((out / "latest.json").exists())
        for h in res["hypotheses"]:
            self.assertIn(h["verdict"], ("adopt", "reject", "keep watching"))


if __name__ == "__main__":
    unittest.main()
