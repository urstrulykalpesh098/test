"""Baseline forecasts that drive the simulator's fair-value path.

Two backends:

* ``timesfm``     Google's TimesFM-3 time-series foundation model, run locally.
                  Optional: ``pip install -r requirements-timesfm.txt``. The
                  code is Apache-2.0, but Google licenses the pretrained
                  weights for NON-COMMERCIAL, NON-PRODUCTION use only.
* ``statistical`` Stdlib random-walk-with-drift on log prices, fitted to the
                  same history. Always available; used when TimesFM is not.

Either way your data stays on this machine. TimesFM only downloads the
model weights (from Hugging Face, once) unless you point
MARKETSIM_TIMESFM_CHECKPOINT at a local copy.
"""
from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from statistics import NormalDist
from typing import Dict, List, Optional

QUANTILES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
DEFAULT_CHECKPOINT = "google/timesfm-3.0-pytorch"
TIMESFM_LICENSE_NOTE = (
    "TimesFM-3 weights are licensed by Google for non-commercial, non-production use only."
)
PRICE_COLUMNS = ("close", "adj close", "adj_close", "price", "value")


@dataclass
class Forecast:
    source: str                     # "timesfm-3" or "statistical"
    history: List[float]
    median: List[float]             # horizon steps after the last history point
    quantiles: Dict[float, List[float]] = field(default_factory=dict)

    @property
    def horizon(self) -> int:
        return len(self.median)

    @property
    def last(self) -> float:
        return self.history[-1]

    def band(self, lo: float = 0.1, hi: float = 0.9):
        return self.quantiles.get(lo), self.quantiles.get(hi)

    def per_step_vol(self) -> Optional[float]:
        """Per-step log volatility implied by the 10-90% band at the horizon."""
        lo, hi = self.band()
        if not lo or not hi or lo[-1] <= 0 or hi[-1] <= lo[-1]:
            return None
        z = NormalDist().inv_cdf(0.9)
        sigma_h = math.log(hi[-1] / lo[-1]) / (2 * z)
        return sigma_h / math.sqrt(self.horizon)

    def relative_path(self, ticks: int, ticks_per_step: int,
                      values: Optional[List[float]] = None) -> List[float]:
        """Forecast (median by default) / last observation, interpolated geometrically per tick."""
        rel = [1.0] + [m / self.last for m in (values if values is not None else self.median)]
        out = []
        for t in range(ticks):
            s = min((t + 1) / ticks_per_step, len(rel) - 1)
            i = min(int(s), len(rel) - 2)
            frac = s - i
            a, b = max(rel[i], 1e-9), max(rel[i + 1], 1e-9)
            out.append(a * (b / a) ** frac)
        return out


# --------------------------------------------------------------------- data
def load_series(path: str | Path, column: Optional[str] = None) -> List[float]:
    """Read one numeric column from a CSV (oldest row first)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"{path}: empty CSV")
        names = {n.strip().lower(): n for n in reader.fieldnames}
        rows = list(reader)
    if column:
        key = names.get(column.strip().lower())
        if key is None:
            raise ValueError(f"{path}: no column {column!r}; columns are {', '.join(reader.fieldnames)}")
    else:
        key = next((names[c] for c in PRICE_COLUMNS if c in names), None)
        if key is None:  # fall back to the last column that is mostly numeric
            for name in reversed(reader.fieldnames):
                if sum(_num(r.get(name)) is not None for r in rows) >= 0.9 * len(rows):
                    key = name
                    break
        if key is None:
            raise ValueError(f"{path}: could not find a numeric column; pass --column")
    values = [v for v in (_num(r.get(key)) for r in rows) if v is not None]
    if len(values) < 32:
        raise ValueError(f"{path}: need at least 32 numeric values in {key!r}, found {len(values)}")
    if min(values) <= 0:
        raise ValueError(f"{path}: {key!r} must be strictly positive (prices, not returns)")
    return values


def _num(x) -> Optional[float]:
    try:
        v = float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ----------------------------------------------------------------- backends
def statistical_forecast(history: List[float], horizon: int, window: int = 250) -> Forecast:
    """Random walk with (shrunk) drift on log prices; lognormal quantiles."""
    recent = history[-(window + 1):]
    rets = [math.log(b / a) for a, b in zip(recent, recent[1:])]
    n = len(rets)
    mu = sum(rets) / n
    sigma = math.sqrt(sum((r - mu) ** 2 for r in rets) / max(1, n - 1))
    mu *= n / (n + 250)  # shrink noisy drift estimates toward zero
    last = history[-1]
    nd = NormalDist()
    quantiles = {
        q: [last * math.exp(mu * h + nd.inv_cdf(q) * sigma * math.sqrt(h)) for h in range(1, horizon + 1)]
        for q in QUANTILES
    }
    return Forecast("statistical", list(history), quantiles[0.5], quantiles)


def timesfm_available() -> bool:
    try:
        import timesfm3  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


_TIMESFM_CACHE: dict = {}


def timesfm_forecast(history: List[float], horizon: int, checkpoint: Optional[str] = None) -> Forecast:
    try:
        import numpy as np
        from timesfm3 import TimesFM3Forecaster
    except ImportError as exc:
        raise RuntimeError(
            "TimesFM is not installed. Run: pip install -r requirements-timesfm.txt"
        ) from exc
    checkpoint = checkpoint or os.environ.get("MARKETSIM_TIMESFM_CHECKPOINT") or DEFAULT_CHECKPOINT
    model = _TIMESFM_CACHE.get(checkpoint)
    if model is None:
        model = TimesFM3Forecaster.from_pretrained(checkpoint, device="cpu")
        _TIMESFM_CACHE[checkpoint] = model
    out = model.predict(
        np.asarray(history, dtype=float), horizon=horizon, return_quantiles=True, make_positive=True,
    )
    median = [float(x) for x in out.forecast]
    quantiles: Dict[float, List[float]] = {}
    levels = list(getattr(getattr(model, "config", None), "quantiles", QUANTILES))
    if out.quantiles is not None:
        q = np.asarray(out.quantiles)
        for j, level in enumerate(levels[: q.shape[-1]]):
            quantiles[round(float(level), 4)] = [float(x) for x in q[:horizon, j]]
    quantiles.setdefault(0.5, median)
    return Forecast("timesfm-3", list(history), median, quantiles)


def make_forecast(history: List[float], horizon: int, model: str = "auto",
                  checkpoint: Optional[str] = None) -> Forecast:
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    if model not in ("auto", "timesfm", "statistical"):
        raise ValueError("model must be auto, timesfm or statistical")
    if model == "statistical" or (model == "auto" and not timesfm_available()):
        return statistical_forecast(history, horizon)
    return timesfm_forecast(history, horizon, checkpoint)


def write_forecast_csv(fc: Forecast, path: Path) -> None:
    levels = sorted(fc.quantiles)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["step", "median"] + [f"q{int(q * 100)}" for q in levels])
        for h in range(fc.horizon):
            w.writerow([h + 1, fc.median[h]] + [fc.quantiles[q][h] for q in levels])
