"""Content-addressed response cache. Doubles as a replay log for deterministic re-runs."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .types import LLMRequest, LLMResponse


class ResponseCache(Protocol):
    def get(self, request: LLMRequest) -> LLMResponse | None: ...
    def put(self, request: LLMRequest, response: LLMResponse) -> None: ...


class DiskCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, request: LLMRequest) -> Path:
        key = request.cache_key()
        return self.root / key[:2] / f"{key}.json"

    def get(self, request: LLMRequest) -> LLMResponse | None:
        path = self._path(request)
        if not path.exists():
            return None
        return LLMResponse.model_validate_json(path.read_text())

    def put(self, request: LLMRequest, response: LLMResponse) -> None:
        path = self._path(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.model_dump_json(indent=2))


class MemoryCache:
    def __init__(self) -> None:
        self._data: dict[str, LLMResponse] = {}

    def get(self, request: LLMRequest) -> LLMResponse | None:
        return self._data.get(request.cache_key())

    def put(self, request: LLMRequest, response: LLMResponse) -> None:
        self._data[request.cache_key()] = response
