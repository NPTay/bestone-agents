from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.config import Settings
from app.content import images
from app.content.images import ImagePlan, ImageResult

PLAN = ImagePlan(kind="stock", stock_query="concrete roof", ai_prompt="generic roof")
IMG_URL = "https://images.pexels.com/photos/1/large2x.jpg"


def _settings(**kw: str) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


@respx.mock
def test_stock_downloads_first_photo(tmp_path: Path) -> None:
    search = respx.get("https://api.pexels.com/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={"photos": [{"photographer": "Jane", "src": {"large2x": IMG_URL}}]},
        )
    )
    respx.get(IMG_URL).mock(return_value=httpx.Response(200, content=b"JPEGDATA"))
    dest = tmp_path / "media"
    res = images.fetch_stock("concrete roof", dest, _settings(PEXELS_API_KEY="k123"))
    assert res is not None
    assert "Jane" in res.note and res.note.startswith("Ảnh: Pexels")
    p = Path(res.paths[0])
    assert p.is_absolute() and p.read_bytes() == b"JPEGDATA"
    assert search.calls[0].request.headers["Authorization"] == "k123"


@respx.mock
def test_stock_none_without_key(tmp_path: Path) -> None:
    route = respx.get("https://api.pexels.com/v1/search")
    assert images.fetch_stock("x", tmp_path, _settings()) is None
    assert not route.called


@respx.mock
def test_stock_none_on_http_error_and_no_key_leak(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    respx.get("https://api.pexels.com/v1/search").mock(return_value=httpx.Response(401))
    assert images.fetch_stock("x", tmp_path, _settings(PEXELS_API_KEY="secretkey")) is None
    assert "secretkey" not in caplog.text


def test_falls_back_to_ai_when_stock_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "fetch_stock", lambda *a, **k: None)
    ai = ImageResult(paths=["/abs/a.png"], note="Ảnh minh họa do AI (Gemini) tạo")
    monkeypatch.setattr(images, "generate_ai", lambda *a, **k: ai)
    assert images.get_morning_image(PLAN, tmp_path, _settings()) is ai


def test_ai_kind_tries_ai_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ai = ImageResult(paths=["/abs/a.png"], note="ai")
    monkeypatch.setattr(images, "generate_ai", lambda *a, **k: ai)

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("stock must not be tried")

    monkeypatch.setattr(images, "fetch_stock", boom)
    plan = ImagePlan(kind="ai", stock_query="q", ai_prompt="p")
    assert images.get_morning_image(plan, tmp_path, _settings()) is ai


def test_both_fail_returns_warning_not_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raises(*a: object, **k: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(images, "fetch_stock", raises)
    monkeypatch.setattr(images, "generate_ai", lambda *a, **k: None)
    res = images.get_morning_image(PLAN, tmp_path, _settings())
    assert res.paths == [] and res.note.startswith("⚠️ Không lấy được ảnh")


class _FakeModels:
    def __init__(self, response: object = None, exc: Exception | None = None) -> None:
        self.response, self.exc, self.kwargs = response, exc, {}

    def generate_content(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.response


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, models: _FakeModels) -> list[str]:
    from google import genai

    built: list[str] = []

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            built.append(api_key)
            self.models = models

    monkeypatch.setattr(genai, "Client", FakeClient)
    return built


def _response(data: bytes | None) -> SimpleNamespace:
    inline = SimpleNamespace(data=data) if data is not None else None
    part = SimpleNamespace(inline_data=inline)
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])


def test_generate_ai_success_writes_png(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    models = _FakeModels(_response(b"PNG"))
    _install_fake_client(monkeypatch, models)
    dest = tmp_path / "media"
    res = images.generate_ai("a roof", dest, _settings(GEMINI_API_KEY="gk"))
    assert res is not None
    assert res.note == "Ảnh minh họa do AI (Gemini) tạo"
    p = Path(res.paths[0])
    assert p.parent == dest.resolve() and p.suffix == ".png" and p.read_bytes() == b"PNG"
    assert models.kwargs["contents"] == "a roof"


def test_generate_ai_no_key_builds_no_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = _install_fake_client(monkeypatch, _FakeModels(_response(b"PNG")))
    assert images.generate_ai("p", tmp_path, _settings()) is None
    assert built == []


@pytest.mark.parametrize("resp", [SimpleNamespace(candidates=[]), _response(None)])
def test_generate_ai_no_image_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resp: object
) -> None:
    _install_fake_client(monkeypatch, _FakeModels(resp))
    assert images.generate_ai("p", tmp_path, _settings(GEMINI_API_KEY="gk")) is None


def test_generate_ai_sdk_error_returns_none_without_key_in_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _install_fake_client(monkeypatch, _FakeModels(exc=RuntimeError("bad key topsecret")))
    assert images.generate_ai("p", tmp_path, _settings(GEMINI_API_KEY="topsecret")) is None
    assert "topsecret" not in caplog.text


def test_first_attempt_exception_still_tries_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raises(*a: object, **k: object) -> None:
        raise RuntimeError("boom")

    ai = ImageResult(paths=["/abs/a.png"], note="ai")
    monkeypatch.setattr(images, "fetch_stock", raises)
    monkeypatch.setattr(images, "generate_ai", lambda *a, **k: ai)
    assert images.get_morning_image(PLAN, tmp_path, _settings()) is ai
