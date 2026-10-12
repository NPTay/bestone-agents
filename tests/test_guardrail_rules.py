import re
from pathlib import Path
from typing import Any

import pytest

from app.guardrails.rules import check_rules, extract_numbers
from app.llm.prompts import PROJECT_ROOT, load_knowledge

KB = load_knowledge()["bestone_knowledge_base.md"]


def _sample() -> dict[str, Any]:
    text = (Path(PROJECT_ROOT) / "agents" / "a2_content.md").read_text(encoding="utf-8")
    section = text.split("## Bài mẫu chuẩn", 1)[1]
    block = re.search(r"^```[^\n]*\n(.*?)^```", section, re.DOTALL | re.MULTILINE)
    assert block is not None
    lines = block.group(1).strip().splitlines()
    hashtag_line = lines[-1]
    body = "\n".join(lines[:-1]).strip()
    return {
        "body": body,
        "title": lines[0].strip(),
        "hashtags": hashtag_line.split(),
        "cta": "Nhắn tin để nhận tài liệu kỹ thuật, hoặc gọi 0904834577.",
        "kb_text": KB,
        "source_texts": [],
        "sources": [],
        "kb_refs": ["2", "3"],
    }


SAMPLE = _sample()


def _checks(**over: Any) -> set[str]:
    return {f.check for f in check_rules(**{**SAMPLE, **over})}


def test_sample_post_passes() -> None:
    assert check_rules(**SAMPLE) == []


def test_warranty_20_years_blocked() -> None:
    f = check_rules(**{**SAMPLE, "body": SAMPLE["body"] + " Bảo hành 20 năm."})
    assert {x.check for x in f} >= {"forbidden_terms", "facts"}


@pytest.mark.parametrize(
    "txt", ["0,2 mm", "0.2 mm", "6 %", "6%", "1.000 kg", "1000 kg", "120 ngày"]
)
def test_kb_numbers_in_any_format_pass(txt: str) -> None:
    assert "facts" not in _checks(body=SAMPLE["body"] + " " + txt)


def test_invented_number_blocked() -> None:
    f = check_rules(**{**SAMPLE, "body": SAMPLE["body"] + " Giảm 95% rò rỉ."})
    facts = [x for x in f if x.check == "facts"]
    assert len(facts) == 1 and "95" in facts[0].message


def test_numbers_from_source_texts_allowed() -> None:
    body = SAMPLE["body"] + " Có 77 công trình."
    assert "facts" in _checks(body=body)
    assert "facts" not in _checks(body=body, source_texts=["Báo cáo nêu 77 công trình."])


def test_gia_tri_allowed_gia_blocked() -> None:
    assert "forbidden_terms" not in _checks(body=SAMPLE["body"] + " Giá trị kỹ thuật. Đánh giá.")
    assert "forbidden_terms" in _checks(body=SAMPLE["body"] + " giá 368.000")
    assert "forbidden_terms" in _checks(body=SAMPLE["body"] + " Giá rẻ.")


def test_ban_vinh_vien_ok_vinh_vien_blocked() -> None:
    assert "forbidden_terms" not in _checks(body=SAMPLE["body"] + " Chống thấm bán vĩnh viễn.")
    assert "forbidden_terms" in _checks(body=SAMPLE["body"] + " Chống thấm vĩnh viễn.")
    assert "forbidden_terms" in _checks(body=SAMPLE["body"] + " Chống thấm VĨNH VIỄN.")


@pytest.mark.parametrize(
    "txt",
    [
        "Bảo hành 10 năm.",
        "Tuổi thọ lên tới 50 năm.",
        "Công trình sử dụng được 30 năm.",
        "Cam kết chất lượng.",
        "Hoàn hảo.",
        "Đột phá công nghệ.",
        "Đạt TCVN.",
        "Tuyệt đối an toàn.",
        "Đảm bảo 100% kín nước.",
        "Số 1 thị trường.",
        "Giá 5 triệu đồng.",
        "Chi phí 100 VND.",
        "Chỉ 50 đồng/m2.",
        "Cách mạng chống thấm.",
        "100% không thấm nước.",
    ],
)
def test_forbidden_terms(txt: str) -> None:
    assert "forbidden_terms" in _checks(body=SAMPLE["body"] + " " + txt)


def test_year_number_not_in_warranty_context_ok() -> None:
    assert "forbidden_terms" not in _checks(
        body=SAMPLE["body"] + " C.G. Engineering thành lập năm 2013."
    )


def test_allowed_100_percent_natural() -> None:
    body = SAMPLE["body"] + " Làm từ 100% nguyên liệu tự nhiên."
    assert "forbidden_terms" not in _checks(body=body)


def test_format_rules() -> None:
    f = check_rules(
        **{
            **SAMPLE,
            "body": "Một bài rất ngắn gọn 😀😀😀 chỉ có sáu mươi chữ " + "chữ " * 5,
            "hashtags": ["#Bestone", "#ChongThamBeTong"],
            "cta": "",
            "title": "Tiêu đề",
        }
    )
    messages = [x.message for x in f if x.check == "format"]
    assert len(messages) == 4, messages
    assert [x.check for x in f] == ["format"] * 4


def test_format_too_long_and_hashtag_count() -> None:
    assert "format" in _checks(body=SAMPLE["body"] + " từ" * 100)
    extra = [*SAMPLE["hashtags"], "#A", "#B"]
    assert "format" in _checks(hashtags=extra)


def test_cta_via_hotline_in_body_ok() -> None:
    body = SAMPLE["body"].replace("Nhắn tin để nhận tài liệu kỹ thuật, hoặc gọi", "Gọi")
    assert "format" not in _checks(body=body, cta="")


def test_no_sources_no_kb_refs() -> None:
    f = check_rules(**{**SAMPLE, "kb_refs": [], "sources": []})
    assert [x.check for x in f] == ["sources"]
    ok = {**SAMPLE, "kb_refs": [], "sources": [{"title": "t", "url": "https://a.vn/x"}]}
    assert check_rules(**ok) == []
    bad = {**SAMPLE, "sources": [{"title": "t", "url": "ftp://a.vn/x"}]}
    assert "sources" in {x.check for x in check_rules(**bad)}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0,2-0,4 mm", {"0.2", "0.4"}),
        ("0,2–0,4 mm", {"0.2", "0.4"}),
        ("0.2 mm", {"0.2"}),
        ("1.000 kg", {"1000"}),
        ("1.000.000", {"1000000"}),
        ("1,22", {"1.22"}),
        ("6%", {"6"}),
        ("6 %", {"6"}),
        ("39 N/mm2", {"39"}),
        ("SiO2 và Al2O3, Fe2O3, Ca(OH)2, CaSiO3, H2O, CO2, 5 m3", {"5"}),
        ("25/03/2021", {"25", "3", "2021"}),
        ("lúc 08:00", {"8", "0"}),
        ("gọi 0904834577", set()),
        ("tháng 2/1991", {"2", "1991"}),
        ("0,20", {"0.2"}),
        ("bảo hành 20 năm", {"20 năm"}),
        ("thành lập năm 2013", {"2013"}),
    ],
)
def test_extract_numbers(text: str, expected: set[str]) -> None:
    assert extract_numbers(text) == expected
