"""Make single-file copies of credit.py and policy.py (common.py inlined) for the Desk Ledger's method/*_script docs.

  python bundle.py OUTDIR   -> OUTDIR/credit.py, OUTDIR/policy.py
"""
import re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMPORT = re.compile(r"try:\n    from common import [^\n]+\nexcept ImportError:[^\n]*\n    from \.common import [^\n]+\n")


def bundle(name):
    common = (HERE / "common.py").read_text().split('"""', 2)[2].strip() + "\n"
    src = (HERE / name).read_text()
    out, n = IMPORT.subn("# --- inlined from common.py ---\n" + common + "# --- end common.py ---\n", src)
    assert n == 1, f"import block not found in {name}"
    return out


if __name__ == "__main__":
    d = Path(sys.argv[1]); d.mkdir(parents=True, exist_ok=True)
    for f in ("credit.py", "policy.py"): (d / f).write_text(bundle(f))
