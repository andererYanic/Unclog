import math

import pytest

from unclog.flow.distributions import arrivals_per_week, cv, mean, service_hours
from unclog.flow.units import hours_per_week, rate_per_week, to_work_hours
from unclog.schemas.diagnosis import Distribution as D


def test_units():
    assert rate_per_week(455, "month") == pytest.approx(105.0)
    assert rate_per_week(3, "days") == 21
    assert to_work_hours(2, "day") == 16 and to_work_hours(30, "min") == 0.5
    assert hours_per_week(160, "month") == pytest.approx(36.92, abs=0.01)
    with pytest.raises(ValueError):
        rate_per_week(1, "fortnight")


@pytest.mark.parametrize(
    "d,m,c",
    [
        (D(kind="fixed", params={"value": 2}), 2, 0),
        (D(kind="exponential", params={"rate": 0.5}), 2, 1),
        (D(kind="gamma", params={"shape": 4, "scale": 0.5}), 2, 0.5),
        (
            D(kind="lognormal", params={"mu": 0, "sigma": 0.5}),
            math.exp(0.125),
            math.sqrt(math.exp(0.25) - 1),
        ),
        (D(kind="uniform", params={"low": 1, "high": 3}), 2, (2 / math.sqrt(12)) / 2),
        (D(kind="empirical", samples=[1, 2, 3]), 2, math.sqrt(2 / 3) / 2),
        (D(kind="lognormal", params={"mean": 30, "cv": 0.4}), 30, 0.4),
    ],
)
def test_mean_and_cv(d, m, c):
    assert mean(d) == pytest.approx(m)
    assert cv(d) == pytest.approx(c)


def test_service_and_arrivals():
    assert service_hours(D(kind="fixed", params={"value": 45}, unit="minute")) == 0.75
    assert arrivals_per_week(D(kind="poisson", params={"rate": 10}, unit="day")) == 70
    # inter-arrival every 2 hours (calendar) -> 84 per week
    assert arrivals_per_week(D(kind="exponential", params={"mean": 2}, unit="hour")) == 84
    with pytest.raises(ValueError, match="params"):
        mean(D(kind="gamma", params={}))
