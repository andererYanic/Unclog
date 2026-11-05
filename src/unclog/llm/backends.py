"""Model backends. The Anthropic backend is the only place the SDK is imported."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol

from .types import LLMRequest, LLMResponse, Usage


class Backend(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...


class AnthropicBackend:
    """Claude via the Anthropic Messages API.

    - adaptive thinking, explicit effort
    - structured outputs via ``output_config.format`` (JSON schema)
    - top-level automatic prompt caching (stable system prompts get cache hits)
    - server-side refusal fallback (``fallbacks="default"``)
    - SDK-level retries for 408/409/429/5xx and connection errors
    """

    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, client: Any | None = None, max_retries: int = 4) -> None:
        if client is None:
            import anthropic  # optional dependency: pip install unclog[llm]

            client = anthropic.Anthropic(max_retries=max_retries)
        self._client = client

    def _schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        import anthropic

        return anthropic.transform_schema(schema)

    def complete(self, request: LLMRequest) -> LLMResponse:
        output_config: dict[str, Any] = {"effort": request.effort}
        if request.output_schema is not None:
            output_config["format"] = {
                "type": "json_schema",
                "schema": self._schema(request.output_schema),
            }
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [m.model_dump() for m in request.messages],
            "thinking": {"type": "adaptive"},
            "output_config": output_config,
            "cache_control": {"type": "ephemeral"},
            "betas": [self.FALLBACK_BETA],
            "fallbacks": "default",
        }
        if request.system:
            kwargs["system"] = request.system

        msg = self._client.beta.messages.create(**kwargs)

        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            raise RuntimeError(f"Model refused request (agent={request.agent}): {details}")

        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        u = msg.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", None) or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", None) or 0,
        )
        return LLMResponse(text=text, model=msg.model, stop_reason=msg.stop_reason, usage=usage)


class FakeBackend:
    """Scripted backend for tests and offline evals. Never touches the network."""

    def __init__(
        self,
        responses: Iterable[str] | Callable[[LLMRequest], str],
        usage: Usage | None = None,
    ) -> None:
        self._fn = responses if callable(responses) else None
        self._queue = None if callable(responses) else list(responses)
        self._usage = usage or Usage(input_tokens=1000, output_tokens=200)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self._fn is not None:
            text = self._fn(request)
        else:
            if not self._queue:
                raise RuntimeError("FakeBackend exhausted")
            text = self._queue.pop(0)
        return LLMResponse(
            text=text, model=request.model, stop_reason="end_turn", usage=self._usage
        )
