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

_HOTLINE_RE = re.compile(r"(?<!\d)(?:\+?84[\s.]?|0)904[\s.]?834[\s.]?577(?!\d)")
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
    text = _norm(text)
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
    # Price-table lines (VND) must not whitelist amounts: prices never belong in posts.
    lines = [ln for ln in kb_text.splitlines() if "vnd" not in ln.casefold()]
    return extract_numbers("\n".join(lines))


_URL_RE = re.compile(r"https?://\S+")


def _check_facts(texts: str, kb_text: str, source_texts: list[str]) -> list[RuleFinding]:
    texts = _URL_RE.sub(" ", texts)  # numeric IDs in news URLs are not claims
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

_L = r"(?<![^\W\d])"  # not preceded by a letter (digits and punctuation allowed)
_R = r"(?![^\W\d])"  # not followed by a letter
_PRICE_UNIT = r"(?:đ(?![^\W\d])|vnd|vnđ|k\b|/\s*m|đồng|tr\b|triệu)"

_TERM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("giá", re.compile(rf"{_L}giá{_R}")),
    ("VND", re.compile(rf"{_L}(?:vnd|vnđ){_R}")),
    ("đồng/m", re.compile(rf"{_L}đồng\s*/\s*m")),
    ("đ/m2", re.compile(rf"{_L}đ\s*/\s*m")),
    ("triệu đồng", re.compile(rf"{_L}triệu\s+đồng{_R}")),
    (
        "số tiền",
        re.compile(rf"(?<![\w.])(?:\d{{1,3}}(?:[.\s]\d{{3}})+\s*{_PRICE_UNIT}|\d+\s*(?:k|tr)\b)"),
    ),
    ("TCVN", re.compile(rf"(?<!\w)tcvn{_R}")),
    ("cam kết", re.compile(r"(?<!\w)cam kết(?!\w)")),
    ("tuyệt đối", re.compile(r"(?<!\w)tuyệt đối(?!\w)")),
    ("hoàn hảo", re.compile(r"(?<!\w)hoàn hảo(?!\w)")),
    ("số 1", re.compile(r"(?<!\w)số\s*1(?!\w|[.,]\d)")),
    ("số một", re.compile(r"(?<!\w)số một(?!\w)")),
    ("đột phá", re.compile(r"(?<!\w)đột phá(?!\w)")),
    ("cách mạng", re.compile(r"(?<!\w)cách mạng(?!\w)")),
    ("trọn đời", re.compile(r"(?<!\w)trọn đời(?!\w)")),
    ("vĩnh cửu", re.compile(r"(?<!\w)vĩnh cửu(?!\w)")),
    ("mãi mãi", re.compile(r"(?<!\w)mãi mãi(?!\w)")),
    ("vĩnh viễn", re.compile(r"(?<!bán )(?<!\w)vĩnh viễn(?!\w)")),
]
_HUNDRED_PERCENT = re.compile(r"100\s*%(?!\s*(?:khoáng thiên nhiên|nguyên liệu tự nhiên))")
_PREFIX = "Cụm từ không được phép trong bài đăng: "


def _split_hashtag(tag: str) -> str:
    """Turn '#BảoHành20Năm' into 'Bảo Hành 20 Năm' so word-based rules apply."""
    out: list[str] = []
    for ch in tag.lstrip("#"):
        if out:
            prev = out[-1]
            if (prev.islower() and ch.isupper()) or (prev.isdigit() != ch.isdigit()):
                out.append(" ")
        out.append(ch)
    return "".join(out)


def _check_forbidden(text: str, hashtags: list[str]) -> list[RuleFinding]:
    text = _HOTLINE_RE.sub(" ", unicodedata.normalize("NFC", text))
    norm = _norm("\n".join([text, *(_split_hashtag(t) for t in hashtags)]))
    found: dict[str, str] = {}
    for sentence in _SENTENCE_SPLIT.split(norm):
        if "bảo hành" in sentence and re.search(r"\d", sentence):
            found.setdefault("bảo hành <số>", _PREFIX + "bảo hành <số>")
        if _CONTEXT_YEARS.search(sentence) and _YEAR_CONTEXT.search(sentence):
            label = "<số> năm (tuổi thọ/bảo hành)"
            found.setdefault(label, _PREFIX + label)
    cleaned = _ALLOWED_PHRASES.sub(" ", norm)
    for label, pattern in _TERM_PATTERNS:
        if pattern.search(cleaned):
            found.setdefault(label, _PREFIX + label)
    if _HUNDRED_PERCENT.search(norm):
        found["100%"] = "Khẳng định 100% không có trong tài liệu"
    return [RuleFinding("forbidden_terms", message) for message in found.values()]


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
        *_check_forbidden(text, hashtags),
        *_check_format(body, hashtags, cta),
        *_check_sources(sources, kb_refs),
    ]


# ----------------------------------------------------------- project names

# Folder names whose short form is how a writer would naturally name the project.
_PROJECT_ALIASES: dict[str, tuple[str, ...]] = {
    "Tòa nhà Kyobo": ("Kyobo",),
    "교보 INSURANCE COMPANY (B1-B4)": ("교보",),
}


def check_project_names(text: str, unverified: list[str]) -> list[RuleFinding]:
    """Flag any unverified picture-folder project named in the text (case-insensitive)."""
    norm = _norm(text)
    findings: list[RuleFinding] = []
    for name in unverified:
        tokens = (name, *_PROJECT_ALIASES.get(name, ()))
        if any(re.search(rf"(?<!\w){re.escape(_norm(t))}(?!\w)", norm) for t in tokens):
            findings.append(
                RuleFinding("facts", f"Nêu tên công trình chưa có thông tin trong tài liệu: {name}")
            )
    return findings
