"""Deterministic guardrail rules for generated posts (pure: no DB, no LLM).

These checks are the last line of defence against invented facts, prices and
warranty promises. They run on the model output regardless of its input.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

HOTLINE = "0904834577"
MANDATORY_HASHTAGS = ("#bestone", "#chongthambetong", "#cgengineeringvietnam")
CTA_PHRASE = "nhắn tin để nhận tài liệu kỹ thuật"
MIN_WORDS = 80
MAX_WORDS = 180
MAX_EMOJI = 2
MIN_HASHTAGS = 3
MAX_HASHTAGS = 5

CheckName = Literal["facts", "forbidden_terms", "format", "sources"]


@dataclass
class RuleFinding:
    check: CheckName
    message: str  # Vietnamese, shown to the director


def _norm(text: str) -> str:
    """NFC-normalise and casefold Vietnamese text for term matching."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", text).casefold())


# ---------------------------------------------------------------- numbers

_HOTLINE_RE = re.compile(r"0904[\s.]?834[\s.]?577")
_HASHTAG_RE = re.compile(r"#\w+")
# A digit run is a number unless glued to a preceding letter/digit/")" (mm2, SiO2, Ca(OH)2).
_NUMBER_RE = re.compile(r"(?<![\w)])\d+(?:[.,]\d+)*(\s*năm(?!\w))?")
_THOUSANDS_RE = re.compile(r"^[1-9]\d{0,2}(?:\.\d{3})+$")


def _canonical(token: str) -> str:
    if _THOUSANDS_RE.match(token):
        return str(int(token.replace(".", "")))
    token = token.replace(",", ".")
    integer, _, fraction = token.partition(".")
    integer = integer.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    return f"{integer}.{fraction}" if fraction else integer


def _ordered_numbers(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text)
    text = _HASHTAG_RE.sub(" ", _HOTLINE_RE.sub(" ", text))
    seen: dict[str, None] = {}
    for match in _NUMBER_RE.finditer(text):
        # "<n> năm" is a duration claim: keep it distinct from the bare number (e.g. 20 kg).
        suffix = " năm" if match.group(1) else ""
        number = _canonical(
            match.group()[: match.end() - match.start() - len(match.group(1) or "")]
        )
        seen.setdefault(number + suffix, None)
    return list(seen)


def extract_numbers(text: str) -> set[str]:
    """Return canonical numeric tokens: dot decimals, no thousands separators or leading zeros."""
    return set(_ordered_numbers(text))


def kb_number_set(kb_text: str) -> set[str]:
    return extract_numbers(kb_text)


def _check_facts(texts: str, kb_text: str, source_texts: list[str]) -> list[RuleFinding]:
    allowed = kb_number_set(kb_text)
    for source in source_texts:
        allowed |= extract_numbers(source)
    return [
        RuleFinding("facts", f"Số liệu không có trong kho tri thức hoặc tin nguồn: {number}")
        for number in _ordered_numbers(texts)
        if number not in allowed
    ]


# --------------------------------------------------------- forbidden terms

_ALLOWED_PHRASES = re.compile(r"(?<!\w)(?:giá trị|đánh giá)(?!\w)")
_SENTENCE_SPLIT = re.compile(r"[!?\n]+|\.(?!\d)|(?<!\d)\.")
_CONTEXT_YEARS = re.compile(r"\d+\s*năm(?!\w)")
_YEAR_CONTEXT = re.compile(r"bảo hành|tuổi thọ|độ bền|sử dụng được")

_TERM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("giá", re.compile(r"(?<!\w)giá(?!\w)")),
    ("VND", re.compile(r"(?<!\w)(?:vnd|vnđ)(?!\w)")),
    ("đồng/m", re.compile(r"(?<!\w)đồng\s*/\s*m")),
    ("đ/m2", re.compile(r"(?<!\w)đ\s*/\s*m")),
    ("triệu đồng", re.compile(r"(?<!\w)triệu\s+đồng(?!\w)")),
    ("TCVN", re.compile(r"(?<!\w)tcvn(?!\w)")),
    ("cam kết", re.compile(r"(?<!\w)cam kết(?!\w)")),
    ("đảm bảo 100%", re.compile(r"(?<!\w)đảm bảo\s*100\s*%")),
    ("tuyệt đối", re.compile(r"(?<!\w)tuyệt đối(?!\w)")),
    ("hoàn hảo", re.compile(r"(?<!\w)hoàn hảo(?!\w)")),
    ("số 1", re.compile(r"(?<!\w)số\s*1(?!\w|[.,]\d)")),
    ("đột phá", re.compile(r"(?<!\w)đột phá(?!\w)")),
    ("cách mạng", re.compile(r"(?<!\w)cách mạng(?!\w)")),
    ("100% không thấm", re.compile(r"100\s*%\s*không thấm")),
    ("vĩnh viễn", re.compile(r"(?<!bán )(?<!\w)vĩnh viễn(?!\w)")),
]


def _check_forbidden(text: str) -> list[RuleFinding]:
    norm = _norm(text)
    found: dict[str, None] = {}
    for sentence in _SENTENCE_SPLIT.split(norm):
        if "bảo hành" in sentence and re.search(r"\d", sentence):
            found.setdefault("bảo hành <số>", None)
        if _CONTEXT_YEARS.search(sentence) and _YEAR_CONTEXT.search(sentence):
            found.setdefault("<số> năm (tuổi thọ/bảo hành)", None)
    cleaned = _ALLOWED_PHRASES.sub(" ", norm)
    for label, pattern in _TERM_PATTERNS:
        if pattern.search(cleaned):
            found.setdefault(label, None)
    return [
        RuleFinding("forbidden_terms", f"Cụm từ không được phép trong bài đăng: {label}")
        for label in found
    ]


# ------------------------------------------------------------------ format

_EMOJI_BASE = "[\U0001f300-\U0001faff\u2600-\u27bf\U0001f000-\U0001f2ff]"
_EMOJI_PART = f"{_EMOJI_BASE}[\ufe0f\U0001f3fb-\U0001f3ff]*"
_EMOJI_RE = re.compile(rf"[\U0001f1e6-\U0001f1ff]{{2}}|{_EMOJI_PART}(?:\u200d{_EMOJI_PART})*")


def count_emoji(text: str) -> int:
    return len(_EMOJI_RE.findall(text))


def _check_format(body: str, hashtags: list[str], cta: str) -> list[RuleFinding]:
    findings: list[RuleFinding] = []
    words = len(body.split())
    if not MIN_WORDS <= words <= MAX_WORDS:
        findings.append(
            RuleFinding(
                "format",
                f"Thân bài có {words} từ, cần từ {MIN_WORDS} đến {MAX_WORDS} từ.",
            )
        )
    emoji = count_emoji(body + " " + cta)
    if emoji > MAX_EMOJI:
        findings.append(RuleFinding("format", f"Bài có {emoji} emoji, tối đa {MAX_EMOJI}."))
    tags = [_norm(t.strip()) for t in hashtags if t.strip()]
    tag_issues: list[str] = []
    if not MIN_HASHTAGS <= len(tags) <= MAX_HASHTAGS:
        tag_issues.append(f"có {len(tags)} hashtag, cần từ {MIN_HASHTAGS} đến {MAX_HASHTAGS}")
    missing = [t for t in MANDATORY_HASHTAGS if t not in tags]
    if missing:
        tag_issues.append("thiếu hashtag bắt buộc: " + ", ".join(missing))
    if tag_issues:
        findings.append(RuleFinding("format", "Hashtag: " + "; ".join(tag_issues) + "."))
    joined = _norm(body + " " + cta)
    if CTA_PHRASE not in joined and HOTLINE not in re.sub(r"[\s.]", "", joined):
        findings.append(
            RuleFinding(
                "format",
                "Thiếu lời kêu gọi hành động: 'Nhắn tin để nhận tài liệu kỹ thuật' hoặc "
                f"hotline {HOTLINE}.",
            )
        )
    return findings


# ----------------------------------------------------------------- sources


def _check_sources(sources: list[dict[str, str]], kb_refs: list[str]) -> list[RuleFinding]:
    findings: list[RuleFinding] = []
    if not kb_refs and not sources:
        findings.append(RuleFinding("sources", "Bài không có nguồn: cần kb_refs hoặc tin nguồn."))
    for source in sources:
        url = source.get("url", "")
        if not url.startswith("http"):
            findings.append(
                RuleFinding("sources", f"Đường dẫn nguồn không hợp lệ: {url or '(trống)'}")
            )
    return findings


def check_rules(
    *,
    body: str,
    title: str,
    hashtags: list[str],
    cta: str,
    kb_text: str,
    source_texts: list[str],
    sources: list[dict[str, str]],
    kb_refs: list[str],
) -> list[RuleFinding]:
    """Run every deterministic rule; an empty list means the post may proceed."""
    text = "\n".join([title, body, cta])
    return [
        *_check_facts(text, kb_text, source_texts),
        *_check_forbidden(text),
        *_check_format(body, hashtags, cta),
        *_check_sources(sources, kb_refs),
    ]
