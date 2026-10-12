"""Load agent system prompts and the knowledge base from the repo's markdown files."""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

AGENT_FILES: dict[str, str] = {
    "orchestrator": "a0_orchestrator.md",
    "research": "a1_research.md",
    "content": "a2_content.md",
    "publisher": "a3_publisher.md",
    "care": "a4_customer_care.md",
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


def load_knowledge(root: Path = PROJECT_ROOT) -> dict[str, str]:
    """Return filename -> content for every knowledge/*.md file."""
    files = sorted((root / "knowledge").glob("*.md"))
    return {p.name: p.read_text(encoding="utf-8") for p in files}
