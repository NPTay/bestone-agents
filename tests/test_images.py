from pathlib import Path

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


def test_falls_back_to_ai_when_stock_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
