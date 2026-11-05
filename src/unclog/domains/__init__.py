"""RACE + back-end domain metrics and heat table (brief §4)."""

from .funnel import StepConversion, conversions, worst_step
from .heat import (
    DirectionCheck,
    DirectionVerdict,
    HeatConfig,
    HeatRow,
    HeatTable,
    Signal,
    SignalKind,
    build_heat_table,
    direction_check,
)
from .priors import ORDER, default_prior
from .report import to_markdown

__all__ = [
    "ORDER",
    "DirectionCheck",
    "DirectionVerdict",
    "HeatConfig",
    "HeatRow",
    "HeatTable",
    "Signal",
    "SignalKind",
    "StepConversion",
    "build_heat_table",
    "conversions",
    "default_prior",
    "direction_check",
    "to_markdown",
    "worst_step",
]
