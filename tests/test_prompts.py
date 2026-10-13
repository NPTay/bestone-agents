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


def test_agent_files_reduced_to_writer_and_judge() -> None:
    assert set(AGENT_FILES) == {"content", "guardrail_judge"}


def test_content_prompt_restates_format_rules() -> None:
    prompt = load_agent_prompt("content")
    for phrase in (
        "Nhắn tin để nhận tài liệu kỹ thuật",
        "0904834577",
        "#Bestone",
        "#ChongThamBeTong",
        "#CGEngineeringVietNam",
        "80-180 từ",
        "theo tài liệu của nhà sản xuất",
    ):
        assert phrase in prompt


def test_missing_block_raises(tmp_path: Path) -> None:
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "a2_content.md").write_text("# no block", encoding="utf-8")
    with pytest.raises(PromptNotFoundError):
        load_agent_prompt("content", root=tmp_path)


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



def test_content_prompt_keeps_cta_and_link_out_of_body() -> None:
    prompt = load_agent_prompt("content")
    assert "KHÔNG đặt lời kêu gọi trong body" in prompt
    assert "KHÔNG đặt link trong body" in prompt
    assert "Cuối body có lời kêu gọi" not in prompt
    assert "tên báo + link" not in prompt
