from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from app.content import images
from app.content.images import ImagePlan, ImageResult

PLAN = ImagePlan(kind="stock", stock_query="concrete roof", ai_prompt="generic roof")
SEARCH_URL = "https://api.unsplash.com/search/photos"
IMG_URL = "https://images.unsplash.com/photo-1?ixid=abc&w=1080"
DL_URL = "https://api.unsplash.com/photos/abc/download?ixid=abc"


def _settings(**kw: str) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def _hit() -> dict[str, object]:
    return {
        "user": {"name": "Jane Doe"},
        "urls": {"regular": IMG_URL},
        "links": {"download_location": DL_URL},
    }


@respx.mock
def test_stock_downloads_first_photo(tmp_path: Path) -> None:
    search = respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json={"results": [_hit()]})
    )
    respx.get(IMG_URL).mock(return_value=httpx.Response(200, content=b"JPEGDATA"))
    track = respx.get(DL_URL).mock(return_value=httpx.Response(200, json={"url": IMG_URL}))
    dest = tmp_path / "media"
    res = images.fetch_stock("concrete roof", dest, _settings(UNSPLASH_ACCESS_KEY="k123"))
    assert res is not None
    assert res.note == "Ảnh: Jane Doe / Unsplash"
    p = Path(res.paths[0])
    assert p.is_absolute() and p.read_bytes() == b"JPEGDATA"
    req = search.calls[0].request
    assert req.headers["Authorization"] == "Client-ID k123"
    assert req.url.params["query"] == "concrete roof"
    assert req.url.params["orientation"] == "landscape"
    # Unsplash API guidelines: trigger the download endpoint when a photo is used.
    assert track.called
    assert track.calls[0].request.headers["Authorization"] == "Client-ID k123"


@respx.mock
def test_stock_still_returns_photo_when_download_tracking_fails(tmp_path: Path) -> None:
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"results": [_hit()]}))
    respx.get(IMG_URL).mock(return_value=httpx.Response(200, content=b"JPEGDATA"))
    respx.get(DL_URL).mock(return_value=httpx.Response(500))
    res = images.fetch_stock("x", tmp_path, _settings(UNSPLASH_ACCESS_KEY="k"))
    assert res is not None and res.paths


@respx.mock
def test_stock_none_when_no_results(tmp_path: Path) -> None:
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"results": []}))
    assert images.fetch_stock("x", tmp_path, _settings(UNSPLASH_ACCESS_KEY="k")) is None


@respx.mock
def test_stock_none_without_key(tmp_path: Path) -> None:
    route = respx.get(SEARCH_URL)
    assert images.fetch_stock("x", tmp_path, _settings()) is None
    assert not route.called


@respx.mock
def test_stock_none_on_http_error_and_no_key_leak(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(401))
    assert images.fetch_stock("x", tmp_path, _settings(UNSPLASH_ACCESS_KEY="secretkey")) is None
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


class _QuotaError(Exception):
    code = 429


def test_gemini_quota_error_pauses_gemini_until_next_local_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frozen_clock: Any
) -> None:
    from datetime import UTC, datetime

    monkeypatch.setattr(images, "_gemini_paused_on", None)
    models = _FakeModels(exc=_QuotaError("429 RESOURCE_EXHAUSTED"))
    built = _install_fake_client(monkeypatch, models)
    s = _settings(GEMINI_API_KEY="g")
    frozen_clock(datetime(2026, 10, 13, 1, 0, tzinfo=UTC))  # 08:00 local
    assert images.generate_ai("p", tmp_path, s) is None
    assert images.generate_ai("p", tmp_path, s) is None
    assert len(built) == 1  # second call skipped: quota exhausted today
    frozen_clock(datetime(2026, 10, 14, 1, 0, tzinfo=UTC))  # next local day
    assert images.generate_ai("p", tmp_path, s) is None
    assert len(built) == 2


def test_gemini_other_errors_do_not_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(images, "_gemini_paused_on", None)
    models = _FakeModels(exc=RuntimeError("boom"))
    built = _install_fake_client(monkeypatch, models)
    s = _settings(GEMINI_API_KEY="g")
    images.generate_ai("p", tmp_path, s)
    images.generate_ai("p", tmp_path, s)
    assert len(built) == 2
