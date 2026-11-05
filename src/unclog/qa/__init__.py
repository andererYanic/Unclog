"""Quality gates G1-G17 and the Critic (brief §16)."""

from .critic import critique
from .gates import GATES, GateResult, run_gates, specificity, to_markdown

__all__ = ["GATES", "GateResult", "critique", "run_gates", "specificity", "to_markdown"]
