"""Random sampling for schema Distributions (seeded numpy Generator; deterministic per seed)."""

from __future__ import annotations

import math

import numpy as np

from ..flow.distributions import cv as dist_cv
from ..flow.distributions import mean as dist_mean
from ..flow.units import to_work_hours
from ..schemas.diagnosis import Distribution

#: calendar hours per unit (for inter-arrival times)
CALENDAR_HOURS = {
    "minute": 1 / 60,
    "hour": 1.0,
    "day": 24.0,
    "week": 168.0,
    "month": 168.0 * 52 / 12,
    "year": 168.0 * 52,
}


def _calendar_hours(value: float, unit: str) -> float:
    u = unit.strip().lower().rstrip("s")
    u = {
        "min": "minute",
        "h": "hour",
        "hr": "hour",
        "d": "day",
        "wk": "week",
        "mo": "month",
        "yr": "year",
    }.get(u, u)
    if u not in CALENDAR_HOURS:
        raise ValueError(f"unknown calendar unit {unit!r}")
    return value * CALENDAR_HOURS[u]


def _lognormal_from_moments(rng: np.random.Generator, mean: float, cv: float) -> float:
    if cv <= 0:
        return mean
    s2 = math.log(1 + cv * cv)
    return float(rng.lognormal(math.log(mean) - s2 / 2, math.sqrt(s2)))


def sample(d: Distribution, rng: np.random.Generator) -> float:
    """One draw in the distribution's own unit (never negative)."""
    k, p = d.kind.lower(), d.params
    if "mean" in p and "cv" in p:
        return _lognormal_from_moments(rng, float(p["mean"]), float(p["cv"]))
    if k == "fixed":
        return float(p.get("value", p.get("mean", 0.0)))
    if k in ("exponential", "poisson"):
        return float(rng.exponential(dist_mean(d)))
    if k == "normal":
        return max(0.0, float(rng.normal(dist_mean(d), dist_cv(d) * dist_mean(d))))
    if k == "lognormal":
        if "mu" in p:
            return float(rng.lognormal(p["mu"], p["sigma"]))
        return _lognormal_from_moments(rng, dist_mean(d), dist_cv(d))
    if k == "gamma":
        if "shape" in p:
            scale = p["scale"] if "scale" in p else 1 / p["rate"]
            return float(rng.gamma(p["shape"], scale))
        m, c = dist_mean(d), dist_cv(d)
        return float(rng.gamma(1 / (c * c), m * c * c)) if c > 0 else m
    if k == "triangular":
        return float(rng.triangular(p["low"], p["mode"], p["high"]))
    if k == "uniform":
        return float(rng.uniform(p["low"], p["high"]))
    if k == "empirical":
        return float(rng.choice(d.samples))
    # unknown kind with a mean: assume exponential-like
    return float(rng.exponential(dist_mean(d)))


def service_hours(d: Distribution, rng: np.random.Generator) -> float:
    return to_work_hours(sample(d, rng), d.unit)


def interarrival_hours(d: Distribution, rng: np.random.Generator, scale: float = 1.0) -> float:
    """Calendar hours until the next arrival. ``poisson``: params.rate per unit."""
    if d.kind.lower() == "poisson":
        rate_per_hour = d.params["rate"] / _calendar_hours(1.0, d.unit) * scale
        return float(rng.exponential(1 / rate_per_hour))
    return _calendar_hours(sample(d, rng), d.unit) / scale
