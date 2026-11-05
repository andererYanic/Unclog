"""Unit conventions for flow math (decision 004).

- Arrival rates are **calendar** rates, normalized to *per week*.
- Service and setup times are **work** time, normalized to *hours*.
- Resource capacity is work hours, normalized to *per week*.
"""

from __future__ import annotations

WORKDAY_HOURS = 8.0
WORKWEEK_HOURS = 40.0

#: how many of a calendar unit fit in one week (rate per unit -> rate per week)
PER_WEEK = {"hour": 168.0, "day": 7.0, "week": 1.0, "month": 12 / 52, "year": 1 / 52}

#: work-time unit -> hours
WORK_HOURS = {"minute": 1 / 60, "hour": 1.0, "day": WORKDAY_HOURS, "week": WORKWEEK_HOURS}


def _norm(unit: str) -> str:
    u = unit.strip().lower()
    aliases = {
        "min": "minute",
        "mins": "minute",
        "h": "hour",
        "hr": "hour",
        "d": "day",
        "wk": "week",
        "mo": "month",
        "yr": "year",
    }
    u = aliases.get(u, u)
    return u[:-1] if u.endswith("s") and u[:-1] in {*PER_WEEK, *WORK_HOURS} else u


def rate_per_week(rate: float, unit: str) -> float:
    u = _norm(unit)
    if u not in PER_WEEK:
        raise ValueError(f"unknown calendar unit {unit!r}; use one of {sorted(PER_WEEK)}")
    return rate * PER_WEEK[u]


def to_work_hours(value: float, unit: str) -> float:
    u = _norm(unit)
    if u not in WORK_HOURS:
        raise ValueError(f"unknown work-time unit {unit!r}; use one of {sorted(WORK_HOURS)}")
    return value * WORK_HOURS[u]


def hours_per_week(hours: float, period: str) -> float:
    """Capacity given per period (e.g. 160 h per month) -> hours per week."""
    return rate_per_week(hours, period)
