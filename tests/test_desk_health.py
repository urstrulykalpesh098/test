import sys, unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyses" / "desk"))
import health as H
import official as O


def run(name, at, summary="ok"):
    return {"name": name, "at": at, "summary": summary}


class Health(unittest.TestCase):
    def test_missing_morning_is_red(self):
        runs = [run("Pre-open check", "2026-11-24T08:50:00-05:00"), run("Midday: no alert", "2026-11-24T12:48:00-05:00"),
                run("Close scorecard", "2026-11-23T16:50:00-05:00"), run("Event engine", "2026-11-23T18:30:00-05:00")]
        h = H.check(runs, [], "2026-11-24")
        self.assertEqual(h["status"], "red")
        self.assertTrue(any("Morning briefing" in i["what"] for i in h["issues"]))

    def test_all_present_is_green_and_holiday_skips_today(self):
        runs = [run("Morning briefing", "2026-11-24T08:30:00-05:00"), run("Pre-open check", "2026-11-24 Tue 08:47 ET"),
                run("Midday: no alert", "2026-11-24T12:48:00-05:00"), run("Close scorecard", "2026-11-23T16:50:00-05:00"),
                run("Event engine", "2026-11-23T18:30:00-05:00"), run("Weekly sentiment desk (Monday Guess)", "2026-11-22 Sun ~19:45 ET")]
        h = H.check(runs, [], "2026-11-24", hub_built="2026-11-24T00:00:00Z", now=datetime(2026, 11, 24, 22, tzinfo=timezone.utc))
        self.assertEqual(h["status"], "green", h["issues"])
        # Thanksgiving: no same-day runs expected; prev trading day is Wed 25 Nov
        self.assertEqual(H.prev_trading("2026-11-27"), "2026-11-25")
        self.assertFalse(H.is_trading("2026-11-26"))

    def test_failures_and_stuck_calls(self):
        runs = [run("Midday: no alert", "2026-11-24T12:48:00-05:00", "S&P 7,200. Book step: chains script failed: HTTP 401"),
                run("Close scorecard", "2026-11-23T16:50:00-05:00", "Yahoo blocked; snippets only. No errors.")]
        preds = [{"_id": "old", "status": "open", "resolves": "2026-11-18"}, {"_id": "new", "status": "open", "resolves": "2026-11-23"}]
        h = H.check(runs, preds, "2026-11-24")
        txt = " ".join(i["what"] for i in h["issues"])
        self.assertIn("script failed", txt)
        self.assertNotIn("Yahoo", txt)          # a blocked news site is not a failure
        self.assertIn("old", txt)
        self.assertNotIn("new", txt.split("resolved:")[-1])

    def test_utc_evening_belongs_to_previous_et_day(self):
        self.assertEqual(H.run_date({"at": "2026-11-25T02:30:00Z"}), "2026-11-24")


class Official(unittest.TestCase):
    def test_parse_and_build(self):
        rows = O.parse("observation_date,SP500\n2026-11-23,7237.17\n2026-11-24,7201.09\n2026-11-25,.\n")
        self.assertEqual(rows, [("2026-11-23", 7237.17), ("2026-11-24", 7201.09)])
        out = O.build({"sp": rows, "vix": [("2026-11-24", 26.36)], "vxv": None})
        self.assertEqual(out["latest"]["sp"], {"date": "2026-11-24", "close": 7201.09, "prev_date": "2026-11-23", "prev": 7237.17})
        self.assertEqual(out["missing"], ["VXVCLS"])
        self.assertEqual(out["closes"]["2026-11-24"], {"sp": 7201.09, "vix": 26.36})


if __name__ == "__main__":
    unittest.main()
