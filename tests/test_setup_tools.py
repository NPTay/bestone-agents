import json
from pathlib import Path

import pytest

from app.cli.setup_tools import check, meta_token, write_env_value
from app.config import Settings

GRAPH = "https://graph.facebook.com/v26.0"
TG_TOKEN = "123:TGSECRET"
TG = f"https://api.telegram.org/bot{TG_TOKEN}"
PAGE_TOKEN = "PAGE_TOKEN_SECRET"
LONG_TOKEN = "LONG_USER_SECRET"
SHORT_TOKEN = "SHORT_USER_SECRET"


class FakeAnthropic:
    """Stands in for anthropic.Anthropic (its HTTP layer is not httpx, so respx can't mock it)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.messages = self

    def create(self, **kwargs: object) -> object:
        self.calls.append({"model": kwargs["model"], "max_tokens": kwargs["max_tokens"]})
        return object()


def _settings(**kw: object) -> Settings:
    # Every key the checks read is explicit, so nothing depends on defaults or the OS env.
    base: dict[str, object] = {
        "ANTHROPIC_API_KEY": "",
        "MODEL_FAST": "claude-haiku-5-5",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_ADMIN_CHAT_ID": "",
        "META_APP_ID": "",
        "META_APP_SECRET": "",
        "META_PAGE_ID": "",
        "META_PAGE_ACCESS_TOKEN": "",
        "META_GRAPH_VERSION": "v26.0",
        "UNSPLASH_ACCESS_KEY": "",
        "GEMINI_API_KEY": "",
    }
    base.update(kw)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def test_meta_token_writes_env_and_prints_no_secret(
    tmp_path: Path,
    respx_mock,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = tmp_path / ".env"
    env.write_bytes(b"A=1\r\nMETA_PAGE_ACCESS_TOKEN=old\r\nB=t\xc3\xa9st\r\n")
    exchange = respx_mock.get(f"{GRAPH}/oauth/access_token").respond(
        200, json={"access_token": LONG_TOKEN, "token_type": "bearer"}
    )
    accounts = respx_mock.get(f"{GRAPH}/me/accounts").respond(
        200,
        json={
            "data": [
                {"id": "999", "name": "Trang khác", "access_token": "OTHER"},
                {"id": "123", "name": "Bestone", "access_token": PAGE_TOKEN},
            ]
        },
    )
    settings = _settings(META_APP_ID="app", META_APP_SECRET="appsecret", META_PAGE_ID="123")

    code = meta_token(settings, SHORT_TOKEN, env)

    assert code == 0
    params = exchange.calls[0].request.url.params
    assert params["grant_type"] == "fb_exchange_token"
    assert params["client_id"] == "app"
    assert params["fb_exchange_token"] == SHORT_TOKEN
    assert accounts.calls[0].request.url.params["access_token"] == LONG_TOKEN
    assert env.read_bytes() == (
        b"A=1\r\nMETA_PAGE_ACCESS_TOKEN=" + PAGE_TOKEN.encode() + b"\r\nB=t\xc3\xa9st\r\n"
    )
    out = capsys.readouterr()
    assert out.out == "Đã lưu token cho Trang: Bestone\n"
    for secret in (PAGE_TOKEN, LONG_TOKEN, SHORT_TOKEN, "appsecret"):
        assert secret not in out.out + out.err


def test_meta_token_page_missing_writes_nothing(
    tmp_path: Path,
    respx_mock,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    respx_mock.get(f"{GRAPH}/oauth/access_token").respond(200, json={"access_token": LONG_TOKEN})
    respx_mock.get(f"{GRAPH}/me/accounts").respond(200, json={"data": []})
    settings = _settings(META_APP_ID="app", META_APP_SECRET="s", META_PAGE_ID="123")

    assert meta_token(settings, SHORT_TOKEN, env) == 1
    assert env.read_text(encoding="utf-8") == "A=1\n"
    out = capsys.readouterr()
    assert "❌" in out.out
    assert LONG_TOKEN not in out.out + out.err


def test_meta_token_graph_error_is_scrubbed(
    tmp_path: Path,
    respx_mock,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    respx_mock.get(f"{GRAPH}/oauth/access_token").respond(
        400, json={"error": {"message": f"Invalid token {SHORT_TOKEN}", "code": 190}}
    )
    settings = _settings(META_APP_ID="app", META_APP_SECRET="s", META_PAGE_ID="123")

    assert meta_token(settings, SHORT_TOKEN, tmp_path / ".env") == 1
    out = capsys.readouterr()
    assert "❌" in out.out
    assert SHORT_TOKEN not in out.out + out.err
    assert not (tmp_path / ".env").exists()


def test_write_env_value_appends_and_strips_bom(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_bytes(b"\xef\xbb\xbfA=1\nB=2")
    write_env_value(env, "META_PAGE_ACCESS_TOKEN", "tok")
    assert env.read_bytes() == b"A=1\nB=2\nMETA_PAGE_ACCESS_TOKEN=tok\n"


def test_check_reports_failures_with_exit_code(
    tmp_path: Path,
    respx_mock,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    pictures = tmp_path / "Picture"
    (pictures / "Du an A").mkdir(parents=True)
    (pictures / "Du an A" / "1.jpg").write_bytes(b"x")
    (pictures / "Du an A" / "2.PNG").write_bytes(b"x")
    (pictures / "Du an A" / "clip.mp4").write_bytes(b"x")
    docs = tmp_path / "Tai Lieu"
    docs.mkdir()
    (docs / "a.pdf").write_bytes(b"x")
    respx_mock.post(f"{TG}/getMe").respond(
        401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}
    )
    settings = _settings(
        ANTHROPIC_API_KEY="anthropic-key",
        TELEGRAM_BOT_TOKEN=TG_TOKEN,
        TELEGRAM_ADMIN_CHAT_ID="42",
        PICTURE_DIR=str(pictures),
        DOCS_DIR=str(docs),
        DRY_RUN=True,
    )

    fake = FakeAnthropic()
    code = check(settings, anthropic_client=fake)

    out = capsys.readouterr().out
    assert code == 1
    assert fake.calls == [{"model": "claude-haiku-5-5", "max_tokens": 5}]
    assert "✅ Anthropic" in out
    assert "❌ Telegram" in out
    assert "❌ Meta" in out  # not configured, but not fatal while DRY_RUN
    assert "2 ảnh" in out
    assert "1 tệp" in out
    assert "DRY_RUN" in out
    for secret in (TG_TOKEN, "TGSECRET", "anthropic-key"):
        assert secret not in out


def test_check_passes_when_required_items_ok(
    tmp_path: Path,
    respx_mock,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    respx_mock.post(f"{TG}/getMe").respond(200, json={"ok": True, "result": {"username": "b"}})
    send = respx_mock.post(f"{TG}/sendMessage").respond(
        200, json={"ok": True, "result": {"message_id": 5}}
    )
    settings = _settings(
        ANTHROPIC_API_KEY="k",
        TELEGRAM_BOT_TOKEN=TG_TOKEN,
        TELEGRAM_ADMIN_CHAT_ID="42",
        PICTURE_DIR=str(tmp_path / "none"),
        DOCS_DIR=str(tmp_path / "none"),
        DRY_RUN=True,
    )

    assert check(settings, anthropic_client=FakeAnthropic()) == 0
    assert json.loads(send.calls[0].request.content)["text"] == "Kiểm tra kết nối OK"
    assert "✅ Telegram" in capsys.readouterr().out


def _fake_genai(monkeypatch: pytest.MonkeyPatch, exc: Exception | None) -> list[dict[str, object]]:
    """Fake genai.Client whose http client 'closes' when the Client object is dropped."""
    from google import genai

    calls: list[dict[str, object]] = []

    class FakeModels:
        def __init__(self, owner: "FakeClient") -> None:
            self.owner = owner

        def generate_content(self, **kw: object) -> object:
            calls.append(kw)
            if exc:
                raise exc
            return object()

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            self.models = FakeModels(self)

    monkeypatch.setattr(genai, "Client", FakeClient)
    return calls


class _Quota(Exception):
    code = 429


def test_check_gemini_explains_quota_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.cli import setup_tools

    _fake_genai(monkeypatch, _Quota("429 RESOURCE_EXHAUSTED"))
    with pytest.raises(setup_tools.SetupError) as err:
        setup_tools._check_gemini(_settings(GEMINI_API_KEY="g"))
    msg = str(err.value)
    assert "429" in msg and "Billing" in msg


def test_check_gemini_ok_makes_one_tiny_image_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.cli import setup_tools

    calls = _fake_genai(monkeypatch, None)
    out = setup_tools._check_gemini(
        _settings(GEMINI_API_KEY="g", GEMINI_IMAGE_MODEL="gemini-x-image")
    )
    assert "gemini-x-image" in out
    assert len(calls) == 1 and calls[0]["model"] == "gemini-x-image"
