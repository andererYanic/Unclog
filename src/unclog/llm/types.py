"""Provider-neutral request/response types for the LLM wrapper."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Effort = Literal["low", "medium", "high", "xhigh", "max"]

DEFAULT_MODEL = "claude-opus-5-5"


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    """One model call. Deterministically hashable, so it can key the cache and replay log."""

    model_config = ConfigDict(extra="forbid")

    model: str = DEFAULT_MODEL
    system: str | None = None
    messages: list[Message]
    max_tokens: int = 16000
    # Opus 5.5 defaults to "medium"; set explicitly so behaviour doesn't drift with model defaults.
    effort: Effort = "high"
    output_schema: dict[str, Any] | None = None
    # Tag for cost attribution, e.g. "constraint_analyst".
    agent: str = "unattributed"

    def cache_key(self) -> str:
        payload = self.model_dump(mode="json", exclude={"agent"})
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class LLMResponse(BaseModel):
    text: str
    model: str
    stop_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    from_cache: bool = False
