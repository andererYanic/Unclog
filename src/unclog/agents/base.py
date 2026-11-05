"""Agent plumbing: versioned prompts, structured calls, post-validation retries (brief §12, §17).

Every agent:
- loads its prompt from ``prompts/<agent>/v<N>.md`` (latest version unless pinned);
- calls the model only through ``LLMClient`` (cost tracking, caching, schema validation);
- runs a deterministic ``check`` on the parsed output; failures go back to the model with the
  error (capped), then escalate;
- returns its result inside an ``AgentOutput`` envelope (agent, prompt_version, confidence,
  open_questions).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from ..llm import LLMClient, LLMRequest
from ..llm.types import Effort, Message
from ..paths import prompts_dir


class AgentEscalation(RuntimeError):
    """Output still failed deterministic checks after retries; needs a human."""


@dataclass(frozen=True)
class Prompt:
    agent: str
    version: str
    text: str
    path: Path


def load_prompt(agent: str, version: int | None = None, root: Path | None = None) -> Prompt:
    folder = (root or prompts_dir()) / agent
    files = sorted(folder.glob("v*.md"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    if not files:
        raise FileNotFoundError(f"no prompt files in {folder}")
    path = folder / f"v{version}.md" if version is not None else files[-1]
    text = path.read_text()
    m = re.search(r"^version:\s*(\S+)", text, re.MULTILINE)
    return Prompt(agent, m.group(1) if m else path.stem, text, path)


@dataclass
class AgentRun[R]:
    result: R
    prompt_version: str
    attempts: int
    cost_usd: float


def run_structured[T: BaseModel, R](
    llm: LLMClient,
    prompt: Prompt,
    user_content: str,
    schema: type[T],
    check: Callable[[T], R],
    effort: Effort = "high",
    max_check_retries: int = 2,
) -> AgentRun[R]:
    """Structured call + deterministic check. ``check`` returns the final result or raises
    ValueError with a message the model can act on."""
    messages = [Message(role="user", content=user_content)]
    cost_before = llm.cost.total_usd
    last_error = ""
    for attempt in range(1, max_check_retries + 2):
        req = LLMRequest(system=prompt.text, messages=messages, effort=effort, agent=prompt.agent)
        parsed = llm.structured(req, schema)
        try:
            result = check(parsed)
            return AgentRun(result, prompt.version, attempt, llm.cost.total_usd - cost_before)
        except ValueError as exc:
            last_error = str(exc)
            messages = [
                *messages,
                Message(role="assistant", content=parsed.model_dump_json()),
                Message(
                    role="user",
                    content=(
                        "Your output parsed, but failed these checks:\n"
                        f"{last_error}\nFix the problems and return the complete corrected JSON."
                    ),
                ),
            ]
    raise AgentEscalation(f"{prompt.agent}: checks still failing after retries: {last_error}")
