"""Setup helpers for the director: find the Telegram chat id, save the Page token, check keys.

Usage (repo root): python -m app.cli.setup_tools telegram-chat-id
                   python -m app.cli.setup_tools meta-token --user-token <token>
                   python -m app.cli.setup_tools check
Never prints a secret.
"""

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anthropic
import httpx

from app.config import Settings, get_settings
from app.meta.graph import GraphClient, GraphError
from app.telegram.bot import TelegramBot, TelegramError

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
TOKEN_KEY = "META_PAGE_ACCESS_TOKEN"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
UNSPLASH_SEARCH = "https://api.unsplash.com/search/photos"
TEST_MESSAGE = "Kiểm tra kết nối OK"
OK, FAIL = "✅", "❌"


class SetupError(Exception):
    """User-facing failure; the message is Vietnamese and contains no secret."""


# --- .env editing ------------------------------------------------------------------


def write_env_value(env_path: Path, key: str, value: str) -> None:
    """Replace `key=` (or append it), keeping every other line byte-for-byte. UTF-8, no BOM."""
    text = env_path.read_bytes().decode("utf-8-sig") if env_path.exists() else ""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    prefix = f"{key}="
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            ending = line[len(line.rstrip("\r\n")) :]
            lines[i] = f"{prefix}{value}{ending}"
            replaced = True
    if not replaced:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        lines.append(f"{prefix}{value}{newline}")
    tmp = env_path.with_name(env_path.name + ".tmp")
    tmp.write_bytes("".join(lines).encode("utf-8"))
    os.replace(tmp, env_path)


# --- meta-token --------------------------------------------------------------------


def _scrub(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _graph_get(
    client: httpx.Client, url: str, params: dict[str, str], secrets: list[str]
) -> dict[str, Any]:
    try:
        resp = client.get(url, params=params)
        body = resp.json()
    except httpx.HTTPError as exc:
        raise SetupError(f"Lỗi kết nối Facebook ({type(exc).__name__})") from None
    except ValueError:
        raise SetupError("Facebook trả về dữ liệu không đọc được") from None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        message = _scrub(str(body["error"].get("message", "")), secrets)
        raise SetupError(f"Facebook báo lỗi: {message}") from None
    if resp.status_code >= 400 or not isinstance(body, dict):
        raise SetupError(f"Facebook báo lỗi HTTP {resp.status_code}") from None
    return body


def _page_token(settings: Settings, user_token: str) -> tuple[str, str]:
    """Return (page name, page token) for META_PAGE_ID from a short-lived user token."""
    missing = [
        name
        for name in ("META_APP_ID", "META_APP_SECRET", "META_PAGE_ID")
        if not getattr(settings, name)
    ]
    if missing:
        raise SetupError(f"Thiếu trong .env: {', '.join(missing)}")
    base = f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}"
    secrets = [user_token, settings.META_APP_SECRET]
    with httpx.Client(timeout=30) as client:
        exchanged = _graph_get(
            client,
            f"{base}/oauth/access_token",
            {
                "grant_type": "fb_exchange_token",
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "fb_exchange_token": user_token,
            },
            secrets,
        )
        long_token = str(exchanged.get("access_token") or "")
        if not long_token:
            raise SetupError("Facebook không trả về token dài hạn")
        secrets.append(long_token)
        url: str | None = f"{base}/me/accounts"
        params = {"access_token": long_token, "fields": "id,name,access_token", "limit": "100"}
        while url:
            body = _graph_get(client, url, params, secrets)
            for page in body.get("data") or []:
                if str(page.get("id")) == settings.META_PAGE_ID and page.get("access_token"):
                    return str(page.get("name") or ""), str(page["access_token"])
            next_url = (body.get("paging") or {}).get("next")
            # The `next` link already carries the query (incl. the token).
            url, params = (str(next_url), {}) if next_url else (None, params)
    raise SetupError(
        f"Tài khoản này không quản lý Trang có ID {settings.META_PAGE_ID} "
        "(hoặc chưa cấp quyền cho Trang khi đăng nhập)"
    )


def meta_token(settings: Settings, user_token: str, env_path: Path) -> int:
    try:
        name, token = _page_token(settings, user_token)
    except SetupError as exc:
        print(f"{FAIL} {exc}")
        return 1
    write_env_value(env_path, TOKEN_KEY, token)
    print(f"Đã lưu token cho Trang: {name}")
    return 0


# --- telegram-chat-id --------------------------------------------------------------


def telegram_chat_id(settings: Settings) -> int:
    if not settings.TELEGRAM_BOT_TOKEN:
        print(f"{FAIL} Chưa có TELEGRAM_BOT_TOKEN trong .env")
        return 1
    bot = TelegramBot(settings.TELEGRAM_BOT_TOKEN, "")
    try:
        updates = bot.get_updates(0, timeout=0)
    except TelegramError as exc:
        print(f"{FAIL} Không đọc được tin nhắn của bot: {exc}")
        return 1
    chats: dict[str, str] = {}
    for update in updates:
        message = update.get("message") or (update.get("callback_query") or {}).get("message")
        chat = (message or {}).get("chat") or {}
        if "id" in chat:
            who = " ".join(
                str(chat[k]) for k in ("first_name", "last_name", "title") if chat.get(k)
            )
            chats[str(chat["id"])] = who
    if not chats:
        print("Chưa thấy tin nhắn nào. Mở Telegram, gửi /start cho bot rồi chạy lại lệnh này.")
        return 1
    for chat_id, who in chats.items():
        print(f"Chat id: {chat_id}  ({who})")
    print("Điền số đó vào .env: TELEGRAM_ADMIN_CHAT_ID=<chat id>")
    return 0


# --- check -------------------------------------------------------------------------


def _check_anthropic(s: Settings, client: Any | None) -> str:
    if not s.ANTHROPIC_API_KEY:
        raise SetupError("chưa có ANTHROPIC_API_KEY")
    if client is None:
        client = anthropic.Anthropic(api_key=s.ANTHROPIC_API_KEY, max_retries=0, timeout=30)
    try:
        client.messages.create(
            model=s.MODEL_FAST, max_tokens=5, messages=[{"role": "user", "content": "Hi"}]
        )
    except anthropic.AuthenticationError:
        raise SetupError("khóa không hợp lệ") from None
    except anthropic.APIStatusError as exc:
        raise SetupError(f"lỗi HTTP {exc.status_code}") from None
    except anthropic.APIConnectionError:
        raise SetupError("không kết nối được") from None
    return f"gọi thử {s.MODEL_FAST} thành công"


def _check_telegram(s: Settings) -> str:
    if not (s.TELEGRAM_BOT_TOKEN and s.TELEGRAM_ADMIN_CHAT_ID):
        raise SetupError("chưa có TELEGRAM_BOT_TOKEN hoặc TELEGRAM_ADMIN_CHAT_ID")
    with httpx.Client(timeout=30) as client:
        bot = TelegramBot(s.TELEGRAM_BOT_TOKEN, s.TELEGRAM_ADMIN_CHAT_ID, client=client)
        try:
            me = bot.get_me()
            bot.send_message(TEST_MESSAGE)
        except TelegramError as exc:
            raise SetupError(str(exc)) from None  # TelegramError never carries the token
    return f"bot @{me.get('username', '?')} đã gửi tin thử"


def _check_meta(s: Settings) -> str:
    if not (s.META_PAGE_ID and s.META_PAGE_ACCESS_TOKEN):
        raise SetupError("chưa có META_PAGE_ID hoặc META_PAGE_ACCESS_TOKEN")
    with httpx.Client(timeout=30) as client:
        try:
            name = GraphClient(s, client=client).page_name()
        except GraphError as exc:
            raise SetupError(exc.message) from None  # GraphError scrubs the token
    return f"Trang: {name}"


def _check_unsplash(s: Settings) -> str:
    if not s.UNSPLASH_ACCESS_KEY:
        raise SetupError("chưa có UNSPLASH_ACCESS_KEY (không bắt buộc)")
    try:
        resp = httpx.get(
            UNSPLASH_SEARCH,
            params={"query": "construction", "per_page": 1},
            headers={
                "Authorization": f"Client-ID {s.UNSPLASH_ACCESS_KEY}",
                "Accept-Version": "v1",
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise SetupError(f"không kết nối được ({type(exc).__name__})") from None
    if resp.status_code != 200:
        raise SetupError(f"lỗi HTTP {resp.status_code}")
    return "tìm ảnh thử thành công"


def _check_gemini(s: Settings) -> str:
    """Generate one tiny image: the only way to see a billing/quota problem (429)."""
    if not s.GEMINI_API_KEY:
        raise SetupError("chưa có GEMINI_API_KEY (không bắt buộc)")
    try:
        from google import genai
        from google.genai import types

        # Keep a reference: a dropped Client closes its HTTP client before the call.
        client = genai.Client(api_key=s.GEMINI_API_KEY)
        client.models.generate_content(
            model=s.GEMINI_IMAGE_MODEL,
            contents="A small plain grey square, no text",
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
    except Exception as exc:  # noqa: BLE001 - SDK errors vary; never print the message
        if getattr(exc, "code", None) == 429:
            raise SetupError(
                f"{s.GEMINI_IMAGE_MODEL}: hết hạn mức tạo ảnh (429). Gói miễn phí không tạo "
                "được ảnh — bật Billing tại https://aistudio.google.com rồi chạy lại. "
                "Trong lúc chờ, bài sáng dùng ảnh Unsplash."
            ) from None
        raise SetupError(
            f"không dùng được mô hình {s.GEMINI_IMAGE_MODEL} ({type(exc).__name__})"
        ) from None
    return f"tạo ảnh thử thành công với {s.GEMINI_IMAGE_MODEL}"


def _count_files(folder: Path, suffixes: set[str] | None) -> int:
    if not folder.is_dir():
        raise SetupError(f"không thấy thư mục {folder}")
    return sum(
        1
        for p in folder.rglob("*")
        if p.is_file() and (suffixes is None or p.suffix.lower() in suffixes)
    )


def _check_pictures(s: Settings) -> str:
    count = _count_files(Path(s.PICTURE_DIR), IMAGE_SUFFIXES)
    if count == 0:
        raise SetupError("thư mục không có ảnh .jpg/.png")
    return f"{count} ảnh"


def _check_docs(s: Settings) -> str:
    count = _count_files(Path(s.DOCS_DIR), None)
    if count == 0:
        raise SetupError("thư mục trống")
    return f"{count} tệp"


def check(settings: Settings, anthropic_client: Any | None = None) -> int:
    """Print one line per item; exit 1 if Anthropic, Telegram or (live mode) Meta fails."""
    items: list[tuple[str, Callable[[Settings], str], bool]] = [
        ("Anthropic (AI viết bài)", lambda s: _check_anthropic(s, anthropic_client), True),
        ("Telegram", _check_telegram, True),
        ("Meta (Trang Facebook)", _check_meta, not settings.DRY_RUN),
        ("Unsplash (ảnh bản quyền)", _check_unsplash, False),
        ("Gemini (ảnh AI)", _check_gemini, False),
        ("Thư mục Picture", _check_pictures, False),
        ("Thư mục Tai Lieu", _check_docs, False),
    ]
    failed = False
    for label, fn, required in items:
        try:
            print(f"{OK} {label}: {fn(settings)}")
        except SetupError as exc:
            print(f"{FAIL} {label}: {exc}")
            failed = failed or required
        except Exception as exc:  # noqa: BLE001 - never print a raw message (may hold a URL)
            print(f"{FAIL} {label}: lỗi {type(exc).__name__}")
            failed = failed or required
    if settings.DRY_RUN:
        print(f"{OK} DRY_RUN=true: chạy thử, chưa đăng thật lên Facebook")
    else:
        print(f"{OK} DRY_RUN=false: bài được duyệt sẽ đăng THẬT lên Facebook")
    return 1 if failed else 0


# --- entry point -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.setup_tools")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("telegram-chat-id", help="Lấy chat id Telegram của Giám đốc")
    token = sub.add_parser("meta-token", help="Đổi token ngắn hạn lấy token Trang dài hạn")
    token.add_argument("--user-token", required=True)
    sub.add_parser("check", help="Kiểm tra các khóa và thư mục")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Relative paths in .env (DATA_DIR, PICTURE_DIR, ...) resolve against the repo root.
    os.chdir(REPO_ROOT)
    get_settings.cache_clear()
    settings = get_settings()
    if args.command == "telegram-chat-id":
        return telegram_chat_id(settings)
    if args.command == "meta-token":
        return meta_token(settings, args.user_token, ENV_FILE)
    return check(settings)


if __name__ == "__main__":
    sys.exit(main())
