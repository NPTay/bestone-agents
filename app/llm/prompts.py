"""Load agent system prompts and the knowledge base from the repo's markdown files."""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

AGENT_FILES: dict[str, str] = {
    "content": "a2_content.md",
    "guardrail_judge": "guardrail_judge.md",
}

_PROMPT_BLOCK = re.compile(r"^```prompt[ \t]*\r?\n(.*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)


class PromptNotFoundError(Exception):
    """Raised when an agent file has no fenced prompt block."""


def load_agent_prompt(agent: str, root: Path = PROJECT_ROOT) -> str:
    """Return the text of the first ```prompt fenced block of the agent's file."""
    path = root / "agents" / AGENT_FILES[agent]
    match = _PROMPT_BLOCK.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise PromptNotFoundError(f"No prompt block in {path.name}")
    return match.group(1).strip()


# Explicit allowlist: review files such as catalogue_proposals.md must never reach a prompt.
RUNTIME_KNOWLEDGE_FILES = (
    "bestone_knowledge_base.md",
    "brand_voice.md",
    "content_pillars.md",
    "guardrails_compliance.md",
)


def load_knowledge(root: Path = PROJECT_ROOT) -> dict[str, str]:
    """Return filename -> content for the runtime knowledge files (allowlist only)."""
    base = root / "knowledge"
    return {
        name: (base / name).read_text(encoding="utf-8")
        for name in RUNTIME_KNOWLEDGE_FILES
        if (base / name).is_file()
    }
