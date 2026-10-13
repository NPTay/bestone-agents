from pathlib import Path

import pytest

from app.llm.prompts import (
    AGENT_FILES,
    PromptNotFoundError,
    load_agent_prompt,
    load_knowledge,
)


def test_all_agents_have_prompt() -> None:
    for agent in AGENT_FILES:
        assert len(load_agent_prompt(agent)) > 50


def test_care_prompt_content() -> None:
    assert "TUYỆT ĐỐI không: báo giá" in load_agent_prompt("care")


def test_missing_block_raises(tmp_path: Path) -> None:
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "a0_orchestrator.md").write_text("# no block", encoding="utf-8")
    with pytest.raises(PromptNotFoundError):
        load_agent_prompt("orchestrator", root=tmp_path)


def test_unknown_agent_raises_key_error() -> None:
    with pytest.raises(KeyError):
        load_agent_prompt("nope")


def test_knowledge_loaded() -> None:
    kb = load_knowledge()
    expected = {
        "bestone_knowledge_base.md",
        "brand_voice.md",
        "content_pillars.md",
        "guardrails_compliance.md",
    }
    assert expected <= kb.keys()

