import json, unittest
from pathlib import Path
from analyses.deskroom import packets

ROOT = Path(__file__).resolve().parents[1]


class DeskRoomPackets(unittest.TestCase):
    def test_build_has_six_seats_with_data(self):
        hub = json.loads((ROOT / "analyses/output/hub/hub_data.json").read_text())
        out = packets.build(hub)
        keys = [s["key"] for s in out["seats"]]
        self.assertEqual(keys, ["vol", "rates", "credit", "cross", "history", "skeptic"])
        vol = out["seats"][0]
        self.assertTrue(any(c["id"] == "VIXCLS" for c in vol["series"]))
        for s in out["seats"]:
            self.assertLess(len(json.dumps(s)), 14000)  # page sends at most 14k chars per seat

    def test_seed_meeting_shape(self):
        m = json.loads((ROOT / "analyses/output/deskroom/seed.json").read_text())
        self.assertEqual(len(m["ceo"]["lines"]), 5)
        self.assertTrue(all(-2 <= p["lean"] <= 2 for p in m["posts"]))


if __name__ == "__main__":
    unittest.main()
