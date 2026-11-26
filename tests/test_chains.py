import subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ChainsSelfTest(unittest.TestCase):
    def test_selftest_passes(self):
        r = subprocess.run([sys.executable, str(ROOT / "analyses/desk/chains.py"), "selftest"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
