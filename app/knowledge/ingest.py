"""Validate that agent prompts and the knowledge base load; print a summary."""

from app.llm.prompts import (
    AGENT_FILES,
    PromptNotFoundError,
    load_agent_prompt,
    load_knowledge,
)

KNOWLEDGE_BASE_FILE = "bestone_knowledge_base.md"


def main() -> int:
    ok = True
    for agent, filename in AGENT_FILES.items():
        try:
            print(f"agent {filename}: {len(load_agent_prompt(agent))} chars")
        except (PromptNotFoundError, OSError) as exc:
            print(f"agent {filename}: ERROR {type(exc).__name__}")
            ok = False
    try:
        knowledge = load_knowledge()
    except OSError as exc:
        print(f"knowledge: ERROR {type(exc).__name__}")
        return 1
    for filename, content in knowledge.items():
        print(f"knowledge {filename}: {len(content)} chars")
    if not knowledge.get(KNOWLEDGE_BASE_FILE, "").strip():
        print(f"knowledge {KNOWLEDGE_BASE_FILE}: missing or empty")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
