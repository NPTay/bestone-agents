"""Anthropic LLM client: structured output, web search, prompt caching, usage logging."""

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Literal, Protocol, TypeVar, cast
from uuid import UUID

import anthropic
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import LlmUsage
from app.db.session import open_session
from app.llm.pricing import cost_usd

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

Reason = Literal["refusal", "max_tokens", "invalid_output", "api_error"]


class LLMError(Exception):
    """Raised when the model call cannot produce usable output."""

    def __init__(self, reason: Reason, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason: Reason = reason


class SearchHit(BaseModel):
    url: str
    title: str
    page_age: str | None = None


class LLMClient(Protocol):
    def structured(
        self,
        *,
        agent: str,
        model: str,
        system: list[str],
        user: str,
        output_model: type[T],
        max_tokens: int = 4000,
        effort: str | None = None,
        job_id: UUID | None = None,
    ) -> T: ...

    def web_search(
        self,
        *,
        agent: str,
        query: str,
        max_uses: int = 3,
        job_id: UUID | None = None,
    ) -> list[SearchHit]: ...


def _record_usage(
    db_factory: Callable[[], Session],
    *,
    agent: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int,
    cache_write: int,
    job_id: UUID | None,
) -> None:
    cost = cost_usd(model, input_tokens, output_tokens, cache_read, cache_write)
    with db_factory() as db:
        db.add(
            LlmUsage(
                agent=agent,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cost_usd=cast(Any, cost),  # Numeric on PG, Float on SQLite
                job_id=job_id,
            )
        )
        db.commit()


class AnthropicLLM:
    def __init__(
        self,
        db_factory: Callable[[], Session],
        settings: Settings,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._db_factory = db_factory
        self._settings = settings
        self._client = client or anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            max_retries=2,
            timeout=float(settings.LLM_TIMEOUT_SECONDS),
        )

    def _create(self, *, agent: str, job_id: UUID | None, **kwargs: Any) -> anthropic.types.Message:
        try:
            response = self._client.messages.create(**kwargs)
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
            # Never include request content; only the exception type.
            logger.warning("Anthropic API error for agent=%s: %s", agent, type(exc).__name__)
            raise LLMError("api_error", type(exc).__name__) from exc
        usage = response.usage
        _record_usage(
            self._db_factory,
            agent=agent,
            model=kwargs["model"],
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read=usage.cache_read_input_tokens or 0,
            cache_write=usage.cache_creation_input_tokens or 0,
            job_id=job_id,
        )
        return cast(anthropic.types.Message, response)

    def structured(
        self,
        *,
        agent: str,
        model: str,
        system: list[str],
        user: str,
        output_model: type[T],
        max_tokens: int = 4000,
        effort: str | None = None,
        job_id: UUID | None = None,
    ) -> T:
        blocks: list[dict[str, Any]] = [{"type": "text", "text": text} for text in system]
        if blocks:
            blocks[-1]["cache_control"] = {"type": "ephemeral"}
        output_config: dict[str, Any] = {
            "format": {
                "type": "json_schema",
                "schema": anthropic.transform_schema(output_model),
            }
        }
        if effort is not None:
            output_config["effort"] = effort

        last_error = ""
        for _attempt in range(2):  # one retry on schema-invalid output
            response = self._create(
                agent=agent,
                job_id=job_id,
                model=model,
                max_tokens=max_tokens,
                system=blocks,
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
            )
            if response.stop_reason in ("refusal", "max_tokens"):
                raise LLMError(cast(Reason, response.stop_reason))
            text = "".join(b.text for b in response.content if b.type == "text")
            try:
                return output_model.model_validate_json(text)
            except ValidationError as exc:
                last_error = f"{exc.error_count()} validation errors"
                logger.warning("Invalid structured output for agent=%s (%s)", agent, last_error)
        raise LLMError("invalid_output", last_error)

    def web_search(
        self,
        *,
        agent: str,
        query: str,
        max_uses: int = 3,
        job_id: UUID | None = None,
    ) -> list[SearchHit]:
        response = self._create(
            agent=agent,
            job_id=job_id,
            model=self._settings.MODEL_QUALITY,
            max_tokens=2000,
            messages=[{"role": "user", "content": query}],
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}],
        )
        if response.stop_reason == "refusal":
            raise LLMError("refusal")
        hits: list[SearchHit] = []
        for block in response.content:
            if block.type != "web_search_tool_result":
                continue
            if not isinstance(block.content, list):  # error object (HTTP 200)
                logger.warning("web_search tool error: %s", block.content.error_code)
                continue
            hits.extend(
                SearchHit(url=r.url, title=r.title, page_age=r.page_age) for r in block.content
            )
        # stop_reason "pause_turn": use hits collected so far; do not loop.
        return hits


class FakeLLM:
    """Offline LLMClient for tests and dry-runs: queued responses keyed by agent."""

    def __init__(
        self,
        responses: dict[str, list[BaseModel | LLMError]],
        hits: list[SearchHit] | None = None,
        db_factory: Callable[[], Session] | None = None,
    ) -> None:
        self.responses = {k: list(v) for k, v in responses.items()}
        self.hits = list(hits or [])
        self.calls: list[dict[str, Any]] = []
        self._db_factory = db_factory

    def _log(self, agent: str, model: str, job_id: UUID | None) -> None:
        if self._db_factory is not None:
            _record_usage(
                self._db_factory,
                agent=agent,
                model=model,
                input_tokens=0,
                output_tokens=0,
                cache_read=0,
                cache_write=0,
                job_id=job_id,
            )

    def structured(
        self,
        *,
        agent: str,
        model: str,
        system: list[str],
        user: str,
        output_model: type[T],
        max_tokens: int = 4000,
        effort: str | None = None,
        job_id: UUID | None = None,
    ) -> T:
        self.calls.append(
            {
                "agent": agent,
                "model": model,
                "system": system,
                "user": user,
                "output_model": output_model,
                "effort": effort,
                "job_id": job_id,
            }
        )
        self._log(agent, model, job_id)
        queue = self.responses.get(agent)
        if not queue:
            raise AssertionError(f"FakeLLM: no queued response for agent {agent!r}")
        item = queue.pop(0)
        if isinstance(item, LLMError):
            raise item
        return cast(T, item)

    def web_search(
        self,
        *,
        agent: str,
        query: str,
        max_uses: int = 3,
        job_id: UUID | None = None,
    ) -> list[SearchHit]:
        self.calls.append({"agent": agent, "query": query, "max_uses": max_uses, "job_id": job_id})
        self._log(agent, "fake", job_id)
        return list(self.hits)


@lru_cache
def get_llm() -> LLMClient | None:
    """Process-wide client, or None when ANTHROPIC_API_KEY is not configured."""
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        return None
    return AnthropicLLM(open_session, settings)
