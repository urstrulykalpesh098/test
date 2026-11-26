import unittest
from analyses.godseye import godseye as g


class GodsEyeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = g.build()

    def test_every_edge_has_evidence_label(self):
        for e in self.d["edges"]:
            self.assertIn(e["kind"], ("tested", "inferred", "mechanical"))
            if e["kind"] == "tested":
                self.assertIn("test", e)
                self.assertIn(e["strength"], ("strong", "moderate", "weak", "none", "contradicts"))

    def test_edges_reference_known_nodes(self):
        ids = {n["id"] for n in self.d["nodes"]}
        for e in self.d["edges"]:
            self.assertIn(e["a"], ids)
            self.assertIn(e["b"], ids)

    def test_snapshots_and_story(self):
        s = self.d["snapshots"]
        self.assertEqual(len(s), g.WEEKS)
        self.assertTrue(s[-1]["story"])
        for p in s[-1]["p"].values():
            self.assertLessEqual(abs(p), 3.0)

    def test_corr_and_labels(self):
        r, n = g.corr(list(range(20)), [2 * x for x in range(20)])
        self.assertAlmostEqual(r, 1.0)
        self.assertEqual(g.strength_label(0.5), "strong")
        self.assertEqual(g.strength_label(-0.3), "contradicts")
        self.assertEqual(g.ordinal(62), "62nd")


if __name__ == "__main__":
    unittest.main()
