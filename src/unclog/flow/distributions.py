"""Mean and coefficient of variation for schema Distributions (deterministic)."""

from __future__ import annotations

import math
import statistics

from ..schemas.diagnosis import Distribution
from .units import rate_per_week, to_work_hours


def _p(d: Distribution, *names: str) -> float:
    for n in names:
        if n in d.params:
            return float(d.params[n])
    raise ValueError(f"{d.kind} distribution needs one of params {names}, got {sorted(d.params)}")


def mean(d: Distribution) -> float:
    """Mean in the distribution's own unit."""
    if "mean" in d.params:
        return float(d.params["mean"])
    k = d.kind.lower()
    if k == "fixed":
        return _p(d, "value")
    if k == "exponential":
        return 1 / _p(d, "rate")
    if k == "normal":
        return _p(d, "mu")
    if k == "lognormal":
        mu, s = _p(d, "mu"), _p(d, "sigma")
        return math.exp(mu + s * s / 2)
    if k == "gamma":
        shape = _p(d, "shape")
        return shape * _p(d, "scale") if "scale" in d.params else shape / _p(d, "rate")
    if k == "triangular":
        return (_p(d, "low") + _p(d, "mode") + _p(d, "high")) / 3
    if k == "uniform":
        return (_p(d, "low") + _p(d, "high")) / 2
    if k == "empirical":
        if not d.samples:
            raise ValueError("empirical distribution needs samples")
        return statistics.fmean(d.samples)
    raise ValueError(f"unsupported distribution kind {d.kind!r}")


def cv(d: Distribution) -> float:
    """Coefficient of variation (stdev / mean); variability is lost capacity (brief §2.4)."""
    if "cv" in d.params:
        return float(d.params["cv"])
    k = d.kind.lower()
    if k == "fixed":
        return 0.0
    if k in ("exponential", "poisson"):
        return 1.0
    if k == "normal":
        return _p(d, "sd", "sigma") / mean(d)
    if k == "lognormal":
        return math.sqrt(math.exp(_p(d, "sigma") ** 2) - 1)
    if k == "gamma":
        return 1 / math.sqrt(_p(d, "shape"))
    if k == "uniform":
        lo, hi = _p(d, "low"), _p(d, "high")
        return (hi - lo) / math.sqrt(12) / mean(d)
    if k == "triangular":
        a, c, b = _p(d, "low"), _p(d, "mode"), _p(d, "high")
        sd = math.sqrt((a * a + b * b + c * c - a * b - a * c - b * c) / 18)
        return sd / mean(d)
    if k == "empirical":
        s = d.samples or []
        return statistics.pstdev(s) / statistics.fmean(s) if len(s) > 1 else 0.0
    return 1.0  # unknown: assume exponential-like variability


def service_hours(d: Distribution) -> float:
    return to_work_hours(mean(d), d.unit)


def arrivals_per_week(d: Distribution) -> float:
    """``poisson`` -> params.rate per ``unit``; any other kind = inter-arrival time in ``unit``."""
    if d.kind.lower() == "poisson":
        return rate_per_week(_p(d, "rate"), d.unit)
    m = mean(d)
    if m <= 0:
        raise ValueError("inter-arrival mean must be > 0")
    return rate_per_week(1 / m, d.unit)
