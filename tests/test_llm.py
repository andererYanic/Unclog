import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from unclog.llm import (
    BudgetExceeded,
    CostTracker,
    LLMClient,
    LLMRequest,
    StructuredOutputError,
    Usage,
    cost_usd,
)
from unclog.llm.backends import AnthropicBackend, FakeBackend
from unclog.llm.cache import DiskCache
from unclog.llm.types import Message


def req(**kw):
    return LLMRequest(messages=[Message(role="user", content="hi")], **kw)


class Out(BaseModel):
    stage: str
    conversion: float


def test_cost_math():
    u = Usage(
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_read_input_tokens=2_000_000,
        cache_creation_input_tokens=1_000_000,
    )
    # 4.00 + 2.00 + 0.40 + 5.00
    assert cost_usd("claude-opus-5-5", u) == pytest.approx(11.40)
    with pytest.raises(KeyError):
        cost_usd("unknown-model", u)


def test_cost_tracking_and_budget():
    tracker = CostTracker(budget_usd=0.01)
    client = LLMClient(FakeBackend(lambda r: "ok"), cost=tracker)
    client.complete(req(agent="intake"))  # 1000 in / 200 out on opus = $0.008
    assert tracker.by_agent["intake"] == pytest.approx(0.008)
    client.complete(req(agent="intake"))
    with pytest.raises(BudgetExceeded):
        client.complete(req(agent="intake"))


def test_cache_hits_are_free(tmp_path):
    backend = FakeBackend(["first", "second"])
    client = LLMClient(backend, cache=DiskCache(tmp_path))
    a = client.complete(req())
    b = client.complete(req())
    assert a.text == b.text == "first" and b.from_cache
    assert len(backend.requests) == 1 and client.cost.calls == 1
    assert req(agent="x").cache_key() == req(agent="y").cache_key()


def test_structured_retries_with_error_then_succeeds():
    backend = FakeBackend(
        ['{"stage": "RACE-A"}', json.dumps({"stage": "RACE-A", "conversion": 0.2})]
    )
    out = LLMClient(backend).structured(req(), Out)
    assert out.conversion == 0.2
    retry = backend.requests[1]
    assert retry.output_schema is not None
    assert "failed validation" in retry.messages[-1].content


def test_structured_escalates_after_cap():
    client = LLMClient(FakeBackend(lambda r: "not json"), max_validation_retries=1)
    with pytest.raises(StructuredOutputError) as exc:
        client.structured(req(), Out)
    assert len(exc.value.attempts) == 2


def test_anthropic_backend_request_shape():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text='{"stage":"RACE-C","conversion":0.1}'),
            ],
            model="claude-opus-5-5",
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                cache_read_input_tokens=None,
                cache_creation_input_tokens=3,
            ),
        )

    fake_sdk = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    client = LLMClient(AnthropicBackend(client=fake_sdk))
    out = client.structured(req(system="You are the Domain Scanner."), Out)
    assert out.stage == "RACE-C"
    assert captured["thinking"] == {"type": "adaptive"}
    assert captured["output_config"]["effort"] == "high"
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert captured["cache_control"] == {"type": "ephemeral"}
    assert captured["fallbacks"] == "default"
    assert captured["system"] == "You are the Domain Scanner."


def test_anthropic_backend_refusal_raises():
    resp = SimpleNamespace(
        content=[],
        model="m",
        stop_reason="refusal",
        stop_details="cyber",
        usage=SimpleNamespace(input_tokens=1, output_tokens=0),
    )
    sdk = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **k: resp)))
    with pytest.raises(RuntimeError, match="refused"):
        AnthropicBackend(client=sdk).complete(req())
