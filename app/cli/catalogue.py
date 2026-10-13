"""Ask Claude to list catalogue facts missing from the KB, into a file for the director to review.

Usage (repo root): python -m app.cli.catalogue
The output file is NEVER read by the running program; the director copies approved items
into knowledge/bestone_knowledge_base.md by hand.
"""

import base64
import os
import sys
from pathlib import Path
from typing import Any

import anthropic

from app.config import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "knowledge" / "catalogue_proposals.md"
KB_PATH = REPO_ROOT / "knowledge" / "bestone_knowledge_base.md"
HEADER = (
    "Bản đề xuất — CHƯA được dùng. "
    "Giám đốc duyệt mục nào thì chép mục đó vào bestone_knowledge_base.md."
)
MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_TOKENS = 8000

INSTRUCTION = (
    "Đọc catalogue PDF đính kèm và so với tài liệu kiến thức hiện có (trong phần system). "
    "Liệt kê bằng markdown tiếng Việt những thông tin có trong catalogue nhưng tài liệu hiện có "
    "chưa có hoặc nói khác đi, chia đúng hai nhóm với tiêu đề:\n"
    "## Bổ sung mới\n"
    "## Khác với tài liệu hiện có\n\n"
    "Quy tắc:\n"
    "- Chỉ ghi thông tin có trong PDF, mỗi mục kèm số trang (ví dụ: (trang 3)).\n"
    "- Không bịa, không suy đoán, không thêm nội dung ngoài PDF.\n"
    "- Giá, bảo hành, tuổi thọ chỉ ghi nếu xuất hiện nguyên văn trong PDF, "
    "và phải đánh dấu \"⚠️ cần Giám đốc xác nhận\".\n"
    "- Nhóm nào không có mục nào thì ghi \"Không có\"."
)


def extract_proposals(client: Any, pdf_path: Path, kb_text: str, model: str) -> str:
    data = base64.standard_b64encode(pdf_path.read_bytes()).decode("ascii")
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": "Tài liệu kiến thức Bestone hiện có (nguồn sự thật hiện tại):\n\n"
                + kb_text,
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": data,
                        },
                    },
                    {"type": "text", "text": INSTRUCTION},
                ],
            }
        ],
    )
    return "".join(b.text for b in response.content if getattr(b, "type", "") == "text")


def run(
    settings: Settings,
    client: Any | None = None,
    output: Path = OUTPUT_PATH,
    kb_path: Path = KB_PATH,
) -> int:
    if not settings.ANTHROPIC_API_KEY:
        print("Chưa có ANTHROPIC_API_KEY trong .env")
        return 1
    pdfs = sorted(p for p in Path(settings.DOCS_DIR).rglob("*") if p.suffix.lower() == ".pdf")
    if not pdfs:
        print("Không tìm thấy file PDF trong thư mục Tai Lieu")
        return 1
    if client is None:
        client = anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS
        )
    kb_text = kb_path.read_text(encoding="utf-8")
    sections: list[str] = []
    for pdf in pdfs:
        if pdf.stat().st_size > MAX_PDF_BYTES:
            print(f"Bỏ qua {pdf.name}: file lớn hơn 30 MB")
            continue
        try:
            body = extract_proposals(client, pdf, kb_text, settings.MODEL_QUALITY)
        except Exception as exc:  # noqa: BLE001 - print the type only, never a message
            print(f"Lỗi khi gọi AI: {type(exc).__name__}")
            return 1
        sections.append(f"# {pdf.name}\n\n{body.strip()}\n")
    if not sections:
        print("Không có file PDF nào xử lý được")
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(HEADER + "\n\n" + "\n".join(sections), encoding="utf-8")
    print(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.chdir(REPO_ROOT)
    get_settings.cache_clear()
    return run(get_settings())


if __name__ == "__main__":
    sys.exit(main())
