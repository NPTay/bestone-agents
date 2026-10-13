import re
from pathlib import Path
from typing import Any

import pytest

from app.guardrails.rules import check_rules, extract_numbers, kb_number_set
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


@pytest.mark.parametrize(
    "txt",
    [
        "Chỉ 368.000đ/m2.",
        "Chỉ 368.000VNĐ/m2.",
        "Chỉ 650.000/m2.",
        "Chỉ 300.000đ.",
        "Chỉ 5 tr/m2.",
        "Chống thấm 100%.",
        "Không thấm 100%.",
        "100% chống thấm.",
        "Bền 20 NĂM.",
        "Chống thấm 30 Năm.",
        "Đạt TCVN9065.",
        "giá368.000",
        "Trọn đời công trình.",
        "Bền vĩnh cửu.",
        "Mãi mãi kín nước.",
        "Sản phẩm số một.",
    ],
)
def test_review_round1_blocked(txt: str) -> None:
    assert _checks(body=SAMPLE["body"] + " " + txt) & {"forbidden_terms", "facts"}


@pytest.mark.parametrize("txt", ["Chỉ 368.000đ/m2.", "Chỉ 650.000/m2.", "Chỉ 5 tr/m2."])
def test_prices_are_forbidden_terms(txt: str) -> None:
    assert "forbidden_terms" in _checks(body=SAMPLE["body"] + " " + txt)


@pytest.mark.parametrize("txt", ["Bền 20 NĂM.", "Chống thấm 30 Năm."])
def test_uppercase_nam_flags_facts_and_terms(txt: str) -> None:
    got = _checks(body=SAMPLE["body"] + " " + txt)
    assert "facts" in got


@pytest.mark.parametrize("tag", ["#BảoHành20Năm", "#GiáRẻ"])
def test_forbidden_in_hashtags(tag: str) -> None:
    assert "forbidden_terms" in _checks(hashtags=[*SAMPLE["hashtags"], tag])


@pytest.mark.parametrize("phrase", ["100% khoáng thiên nhiên", "100% nguyên liệu tự nhiên"])
def test_100_percent_natural_phrases_ok(phrase: str) -> None:
    assert "forbidden_terms" not in _checks(body=SAMPLE["body"] + f" Làm từ {phrase}.")


@pytest.mark.parametrize(
    "hotline", ["+84 904 834 577", "+84904834577", "0904 834 577", "0904.834.577"]
)
def test_hotline_variants_excluded_from_facts(hotline: str) -> None:
    assert extract_numbers(f"gọi {hotline}") == set()
    assert _checks(body=SAMPLE["body"] + f" Gọi {hotline}.") == set()


@pytest.mark.parametrize(
    "txt",
    [
        "Phát thải 1,22 kg CO2eq/m2.",
        "So với 20,25.",
        "Vết nứt 0,2 đến 0,4 mm.",
        "Trộn 6% khối lượng xi măng.",
        "Sau 120 ngày.",
        "11/30 công ty.",
        "Túi 20 kg.",
        "Bao 1.000 kg.",
        "Cường độ 39 N/mm2.",
        "Áp lực 1 MPa.",
        "Trong 90 ngày.",
    ],
)
def test_kb_facts_produce_no_findings(txt: str) -> None:
    assert _checks(body=SAMPLE["body"] + " " + txt) == set()


def test_kb_price_numbers_not_whitelisted() -> None:
    assert not {"368000", "525000", "650000"} & kb_number_set(KB)


# ------------------------------------------------------------ project names


def test_check_project_names_flags_unverified_kyobo() -> None:
    from app.guardrails.rules import check_project_names

    text = "Bestone đã được dùng cho công trình Kyobo tại Hàn Quốc."
    findings = check_project_names(text, ["Tòa nhà Kyobo"])
    assert len(findings) == 1
    assert findings[0].check == "facts"
    assert findings[0].message == (
        "Nêu tên công trình chưa có thông tin trong tài liệu: Tòa nhà Kyobo"
    )


def test_check_project_names_korean_token_and_case() -> None:
    from app.guardrails.rules import check_project_names

    unverified = ["교보 INSURANCE COMPANY (B1-B4)", "Warehouse - 80m of basement"]
    assert len(check_project_names("Dự án 교보 dùng Bestone.", unverified)) == 1
    assert len(check_project_names("WAREHOUSE - 80M OF BASEMENT", unverified)) == 1
    assert check_project_names("Kho hàng tầng hầm sâu.", unverified) == []
    assert check_project_names("Kyobo", []) == []


def test_news_url_numeric_id_not_a_fact() -> None:
    url = "https://baoxaydung.vn/ham-chui-bi-tham-nuoc-192241013.htm"
    assert "facts" not in _checks(body=SAMPLE["body"] + f" Theo Báo Xây Dựng ({url}).")
    f = check_rules(**{**SAMPLE, "body": SAMPLE["body"] + f" {url} Giảm 95% rò rỉ."})
    facts = [x for x in f if x.check == "facts"]
    assert len(facts) == 1 and "95" in facts[0].message
