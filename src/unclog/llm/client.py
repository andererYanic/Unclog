"""LLMClient: the single entry point agents use to call a model."""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .backends import Backend
from .cache import ResponseCache
from .cost import CostTracker
from .pricing import cost_usd
from .types import DEFAULT_MODEL, LLMRequest, LLMResponse, Message

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """Model output failed schema validation after all retries; escalate to a human."""

    def __init__(self, message: str, attempts: list[str]) -> None:
        super().__init__(message)
        self.attempts = attempts


class LLMClient:
    def __init__(
        self,
        backend: Backend,
        cost: CostTracker | None = None,
        cache: ResponseCache | None = None,
        max_validation_retries: int = 2,
        default_model: str | None = None,
        on_call=None,
    ) -> None:
        self.backend = backend
        self.cost = cost or CostTracker()
        self.cache = cache
        self.max_validation_retries = max_validation_retries
        # Routing / model-change evals: replaces the default model where the caller didn't pick.
        self.default_model = default_model
        # Audit hook: called with (request, response) after every call, cached or not (§14).
        self.on_call = on_call

    def complete(self, request: LLMRequest) -> LLMResponse:
        if self.default_model and request.model == DEFAULT_MODEL:
            request = request.model_copy(update={"model": self.default_model})
        if self.cache is not None and (hit := self.cache.get(request)) is not None:
            hit = hit.model_copy(update={"from_cache": True})
            if self.on_call:
                self.on_call(request, hit)
            return hit
        self.cost.check()
        response = self.backend.complete(request)
        # Price by the requested model; a server-side fallback may bill differently.
        usd = cost_usd(request.model, response.usage)
        response = response.model_copy(update={"cost_usd": usd})
        self.cost.record(request.agent, usd)
        if self.cache is not None:
            self.cache.put(request, response)
        if self.on_call:
            self.on_call(request, response)
        return response

    def structured(self, request: LLMRequest, schema: type[T]) -> T:
        """Call with a JSON-schema output constraint and validate into ``schema``.

        On validation failure, retry with the error appended (brief §17), capped by
        ``max_validation_retries``; then raise StructuredOutputError for escalation.
        """
        req = request.model_copy(update={"output_schema": schema.model_json_schema()})
        attempts: list[str] = []
        for _ in range(self.max_validation_retries + 1):
            resp = self.complete(req)
            attempts.append(resp.text)
            try:
                return schema.model_validate(json.loads(resp.text))
            except (json.JSONDecodeError, ValidationError) as exc:
                feedback = (
                    "Your previous output failed validation against the required schema.\n"
                    f"Errors:\n{exc}\nReturn corrected JSON only."
                )
                req = req.model_copy(
                    update={
                        "messages": [
                            *req.messages,
                            Message(role="assistant", content=resp.text),
                            Message(role="user", content=feedback),
                        ]
                    }
                )
        raise StructuredOutputError(
            f"{schema.__name__}: output invalid after {len(attempts)} attempts (agent="
            f"{request.agent}); escalate",
            attempts,
        )
