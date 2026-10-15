import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel
from sqlalchemy import orm

from app.config import Settings
from app.db.models import LlmUsage
from app.llm.client import AnthropicLLM, FakeLLM, LLMError, SearchHit, get_llm
from app.llm.pricing import PRICES, cost_usd

SONNET = "claude-sonnet-5-5"


class Demo(BaseModel):
    x: int


def _settings() -> Settings:
    return Settings(DATABASE_URL="sqlite://", SESSION_SECRET_KEY="s", ANTHROPIC_API_KEY="k")


def _message(
    content: list[dict[str, Any]], stop_reason: str = "end_turn", **usage: int | None
) -> dict[str, Any]:
    u: dict[str, Any] = {"input_tokens": 10, "output_tokens": 5}
    u.update(usage)
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": SONNET,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": u,
    }


def _text(t: str) -> dict[str, Any]:
    return {"type": "text", "text": t}


class Mock:
    """Offline Anthropic transport: queued JSON responses, recorded request bodies."""

    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        self.bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=self.responses.pop(0))

    def llm(self, db_factory: Callable[[], orm.Session]) -> AnthropicLLM:
        client = anthropic.Anthropic(
            api_key="test",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self)),
        )
        return AnthropicLLM(db_factory, _settings(), client=client)


def test_cost_usd_sonnet() -> None:
    assert cost_usd(SONNET, 1_000_000, 100_000, 0, 0) == Decimal("3.00")
    assert cost_usd(SONNET, 0, 0, 1_000_000, 1_000_000) == Decimal("2.70")
    assert cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000, 0, 0) == Decimal("0.60")
    assert PRICES["claude-haiku-5-5"].cache_write == Decimal("0.125")


def test_cost_usd_unknown_model_is_zero(caplog: pytest.LogCaptureFixture) -> None:
    assert cost_usd("nope", 5, 5, 5, 5) == Decimal(0)
    assert "nope" in caplog.text


def test_structured_parses_and_logs_usage(
    db: orm.Session, db_factory: Callable[[], orm.Session]
) -> None:
    mock = Mock(_message([_text('{"x": 1}')], cache_read_input_tokens=None))
    out = mock.llm(db_factory).structured(
        agent="content", model=SONNET, system=["P", "KB"], user="u", output_model=Demo
    )
    assert out == Demo(x=1)
    row = db.query(LlmUsage).one()
    assert (row.agent, row.model, row.input_tokens, row.output_tokens) == (
        "content",
        SONNET,
        10,
        5,
    )
    assert row.cache_read_tokens == 0
    assert float(row.cost_usd) == pytest.approx(10 * 2 / 1e6 + 5 * 10 / 1e6)


def test_request_shape(db_factory: Callable[[], orm.Session]) -> None:
    mock = Mock(_message([_text('{"x": 1}')]))
    mock.llm(db_factory).structured(
        agent="content",
        model=SONNET,
        system=["P", "KB"],
        user="u",
        output_model=Demo,
        effort="low",
    )
    body = mock.bodies[0]
    assert body["model"] == SONNET
    assert body["system"][0] == {"type": "text", "text": "P"}
    assert body["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"] == [{"role": "user", "content": "u"}]
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    for forbidden in ("tool_choice", "thinking", "temperature"):
        assert forbidden not in body


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_bad_stop_reason_raises_and_logs(
    stop: str, db: orm.Session, db_factory: Callable[[], orm.Session]
) -> None:
    mock = Mock(_message([_text('{"x": 1}')], stop_reason=stop))
    with pytest.raises(LLMError) as e:
        mock.llm(db_factory).structured(
            agent="a", model=SONNET, system=["P"], user="u", output_model=Demo
        )
    assert e.value.reason == stop
    assert db.query(LlmUsage).count() == 1
    assert len(mock.bodies) == 1


def test_invalid_output_retries_once_then_fails(
    db: orm.Session, db_factory: Callable[[], orm.Session]
) -> None:
    mock = Mock(_message([_text("not json")]), _message([_text('{"x": "bad"}')]))
    with pytest.raises(LLMError) as e:
        mock.llm(db_factory).structured(
            agent="a", model=SONNET, system=["P"], user="u", output_model=Demo
        )
    assert e.value.reason == "invalid_output"
    assert len(mock.bodies) == 2
    assert db.query(LlmUsage).count() == 2


def test_invalid_then_valid_succeeds(db_factory: Callable[[], orm.Session]) -> None:
    mock = Mock(_message([_text("oops")]), _message([_text('{"x": 7}')]))
    out = mock.llm(db_factory).structured(
        agent="a", model=SONNET, system=["P"], user="u", output_model=Demo
    )
    assert out == Demo(x=7)


def test_api_error_wrapped(db_factory: Callable[[], orm.Session]) -> None:
    def boom(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, json={"type": "error", "error": {"type": "api_error"}})

    client = anthropic.Anthropic(
        api_key="t", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(boom))
    )
    llm = AnthropicLLM(db_factory, _settings(), client=client)
    with pytest.raises(LLMError) as e:
        llm.structured(agent="a", model=SONNET, system=["P"], user="u", output_model=Demo)
    assert e.value.reason == "api_error"


def _search_result(content: Any) -> dict[str, Any]:
    return {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": content}


def test_web_search_collects_hits(db: orm.Session, db_factory: Callable[[], orm.Session]) -> None:
    results = [
        {
            "type": "web_search_result",
            "url": "https://a.vn/x",
            "title": "A",
            "page_age": "2 days ago",
            "encrypted_content": "enc",
        },
        {
            "type": "web_search_result",
            "url": "https://b.vn/y",
            "title": "B",
            "page_age": None,
            "encrypted_content": "enc",
        },
    ]
    mock = Mock(_message([_text("ok"), _search_result(results)]))
    out = mock.llm(db_factory).web_search(agent="research", query="chống thấm")
    assert out == [
        SearchHit(url="https://a.vn/x", title="A", page_age="2 days ago"),
        SearchHit(url="https://b.vn/y", title="B", page_age=None),
    ]
    tool = mock.bodies[0]["tools"][0]
    assert tool["type"] == "web_search_20260209"
    assert tool["name"] == "web_search"
    assert tool["max_uses"] == 3
    assert mock.bodies[0]["model"] == SONNET
    assert "tool_choice" not in mock.bodies[0]
    assert db.query(LlmUsage).count() == 1


def test_web_search_error_object_yields_no_hits(db_factory: Callable[[], orm.Session]) -> None:
    err = {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}
    mock = Mock(_message([_search_result(err)]))
    assert mock.llm(db_factory).web_search(agent="research", query="q") == []


def test_web_search_pause_turn_returns_collected(db_factory: Callable[[], orm.Session]) -> None:
    results = [
        {"type": "web_search_result", "url": "https://a.vn", "title": "A", "encrypted_content": "e"}
    ]
    mock = Mock(_message([_search_result(results)], stop_reason="pause_turn"))
    hits = mock.llm(db_factory).web_search(agent="research", query="q")
    assert [h.url for h in hits] == ["https://a.vn"]
    assert len(mock.bodies) == 1


def test_fake_llm(db: orm.Session, db_factory: Callable[[], orm.Session]) -> None:
    fake = FakeLLM(
        {"content": [Demo(x=2), LLMError("refusal")]},
        hits=[SearchHit(url="u", title="t", page_age=None)],
        db_factory=db_factory,
    )
    kw: dict[str, Any] = {"model": SONNET, "system": ["P"], "user": "u", "output_model": Demo}
    assert fake.structured(agent="content", **kw) == Demo(x=2)
    with pytest.raises(LLMError):
        fake.structured(agent="content", **kw)
    assert fake.web_search(agent="research", query="q")[0].url == "u"
    assert [c["agent"] for c in fake.calls] == ["content", "content", "research"]
    assert db.query(LlmUsage).count() == 3


def test_get_llm_none_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    get_llm.cache_clear()
    assert get_llm() is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    get_settings.cache_clear()
    get_llm.cache_clear()
    assert isinstance(get_llm(), AnthropicLLM)
    get_llm.cache_clear()
    get_settings.cache_clear()


def test_web_search_explicitly_instructs_the_model_to_search(
    db_factory: Callable[[], orm.Session],
) -> None:
    # Seen live 15/10/2026: a bare query made the model answer from memory (0 hits).
    mock = Mock(_message([_search_result([])]))
    mock.llm(db_factory).web_search(agent="research", query="thấm dột tầng hầm")
    content = mock.bodies[0]["messages"][0]["content"]
    assert "thấm dột tầng hầm" in content
    assert "web_search" in content and "Không trả lời từ kiến thức" in content


def test_web_search_restricts_to_allowed_domains(db_factory: Callable[[], orm.Session]) -> None:
    mock = Mock(_message([_search_result([])]))
    mock.llm(db_factory).web_search(
        agent="research", query="q", allowed_domains=["vnexpress.net", "tuoitre.vn"]
    )
    [tool] = mock.bodies[0]["tools"]
    assert tool["allowed_domains"] == ["vnexpress.net", "tuoitre.vn"]


def test_web_search_without_domains_sends_no_filter(db_factory: Callable[[], orm.Session]) -> None:
    mock = Mock(_message([_search_result([])]))
    mock.llm(db_factory).web_search(agent="research", query="q")
    assert "allowed_domains" not in mock.bodies[0]["tools"][0]


def test_web_search_asks_for_recent_news(db_factory: Callable[[], orm.Session]) -> None:
    mock = Mock(_message([_search_result([])]))
    mock.llm(db_factory).web_search(agent="research", query="q")
    assert "3 tháng gần đây" in mock.bodies[0]["messages"][0]["content"]
