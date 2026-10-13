import base64
from pathlib import Path
from types import SimpleNamespace

from app.cli import catalogue
from app.config import Settings
from app.llm.prompts import PROJECT_ROOT, load_knowledge

PDF_BYTES = b"%PDF-1.4 fake"


class FakeClient:
    """Stands in for anthropic.Anthropic (its transport is not httpx, so respx can't mock it)."""

    def __init__(self, text: str = "## Bổ sung mới\n- Điểm A (trang 2)") -> None:
        self.calls: list[dict[str, object]] = []
        self.messages = self
        self._text = text

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


def test_extract_sends_pdf_document_block(tmp_path: Path) -> None:
    pdf = tmp_path / "cat.pdf"
    pdf.write_bytes(PDF_BYTES)
    client = FakeClient()
    out = catalogue.extract_proposals(client, pdf, "KB TEXT", "model-x")
    assert "Điểm A" in out
    call = client.calls[0]
    assert call["model"] == "model-x"
    assert "KB TEXT" in str(call["system"])
    content = call["messages"][0]["content"]  # type: ignore[index]
    block = content[0]
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"
    assert base64.standard_b64decode(block["source"]["data"]) == PDF_BYTES
    assert content[1]["type"] == "text"
    assert "## Bổ sung mới" in content[1]["text"]
    assert "## Khác với tài liệu hiện có" in content[1]["text"]


def test_runtime_knowledge_excludes_proposals(tmp_path: Path) -> None:
    root = tmp_path
    (root / "knowledge").mkdir()
    for name in (
        "bestone_knowledge_base.md",
        "brand_voice.md",
        "content_pillars.md",
        "guardrails_compliance.md",
        "catalogue_proposals.md",
    ):
        (root / "knowledge" / name).write_text("x", encoding="utf-8")
    kb = load_knowledge(root)
    assert "catalogue_proposals.md" not in kb
    assert len(kb) == 4
    assert "catalogue_proposals.md" not in load_knowledge(PROJECT_ROOT)


def test_run_writes_review_file_only(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    (docs / "sub" / "a.pdf").write_bytes(PDF_BYTES)
    (docs / "note.txt").write_text("ignore", encoding="utf-8")
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    kb = knowledge / "bestone_knowledge_base.md"
    kb.write_text("KB", encoding="utf-8")
    out = knowledge / "catalogue_proposals.md"
    settings = Settings(ANTHROPIC_API_KEY="k", DOCS_DIR=str(docs), _env_file=None)
    client = FakeClient()
    assert catalogue.run(settings, client, output=out, kb_path=kb) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith(catalogue.HEADER)
    assert "# a.pdf" in text and "Điểm A" in text
    assert kb.read_text(encoding="utf-8") == "KB"
    assert sorted(p.name for p in knowledge.iterdir()) == [
        "bestone_knowledge_base.md",
        "catalogue_proposals.md",
    ]


def test_run_without_key_or_pdfs(tmp_path: Path, capsys: object) -> None:
    settings = Settings(ANTHROPIC_API_KEY="", DOCS_DIR=str(tmp_path), _env_file=None)
    assert catalogue.run(settings, None, output=tmp_path / "o.md", kb_path=tmp_path / "k.md") == 1
    settings = Settings(ANTHROPIC_API_KEY="k", DOCS_DIR=str(tmp_path), _env_file=None)
    out, kb = tmp_path / "o.md", tmp_path / "k.md"
    assert catalogue.run(settings, FakeClient(), output=out, kb_path=kb) == 1
    assert not out.exists()
