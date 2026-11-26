"""Shared math for the Eye View lab. Stdlib only."""
import math, statistics as st

Z80 = 1.2815515655446004


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def logret(a, b):
    return math.log(b / a)


def brier(pairs):
    pairs = list(pairs)
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else None


def rate(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def wilson(k, n, z=1.96):
    """95% interval for a hit rate."""
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 4), round(c + h, 4))


def quantiles(xs, qs=(0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)):
    s = sorted(xs)
    if not s:
        return {}
    out = {}
    for q in qs:
        i = q * (len(s) - 1)
        lo, hi = int(math.floor(i)), int(math.ceil(i))
        out[str(q)] = s[lo] + (s[hi] - s[lo]) * (i - lo)
    return out


def ewma_vol(rets, lam=0.94):
    """RiskMetrics EWMA daily vol after each return (list aligned to rets)."""
    out, v = [], None
    for r in rets:
        v = r * r if v is None else lam * v + (1 - lam) * r * r
        out.append(math.sqrt(v))
    return out


def vix_bucket(v):
    return "<15" if v < 15 else "15-20" if v < 20 else "20-25" if v < 25 else "25-35" if v < 35 else "35+"


def fit_logit(xs, ys, iters=25, ridge=1e-3):
    """One-feature logistic regression by Newton. Returns (a, b)."""
    a = b = 0.0
    for _ in range(iters):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            p = 1 / (1 + math.exp(-(a + b * x)))
            w = p * (1 - p)
            ga += y - p; gb += (y - p) * x
            haa += w; hab += w * x; hbb += w * x * x
        gb -= ridge * b; hbb += ridge
        det = haa * hbb - hab * hab
        if det <= 1e-12:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        a += da; b += db
        if abs(da) + abs(db) < 1e-9:
            break
    return a, b


def logit_p(a, b, x):
    z = max(-30, min(30, a + b * x))
    return 1 / (1 + math.exp(-z))


def r4(x):
    return None if x is None else round(x, 4)
