import re
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_env_example_matches_settings() -> None:
    keys: set[str] = set()
    for raw in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            keys.add(line.split("=", 1)[0].strip())
    assert keys == set(Settings.model_fields)


def test_install_guide_mentions_every_setup_command() -> None:
    guide = (ROOT / "docs" / "HUONG_DAN_CAI_DAT.md").read_text(encoding="utf-8")
    for needle in (
        "telegram-chat-id",
        "meta-token",
        "check",
        "install_autostart.ps1",
        "DRY_RUN",
        "app.cli.catalogue",
        "app.log",
        "Token Facebook hết hạn",
        "không rõ đã đăng",
        "bị gián đoạn lúc đang đăng",
    ):
        assert needle in guide, needle


def test_privacy_policy_is_standalone_html() -> None:
    html = (ROOT / "docs" / "chinh_sach_quyen_rieng_tu.html").read_text(encoding="utf-8")
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert '<html lang="vi">' in html
    assert '<meta charset="utf-8">' in html.lower()
    assert "0904834577" in html and "https://cgengvn.com" in html
    assert not re.search(r"""(src|href)\s*=\s*["']https?://(?!cgengvn\.com)""", html)
    assert "<script" not in html.lower()
