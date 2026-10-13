"""Morning image sourcing: licensed stock (Unsplash) or a Gemini illustration."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel

from app.config import Settings

log = logging.getLogger(__name__)

UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
NO_IMAGE_NOTE = (
    "⚠️ Không lấy được ảnh (kho ảnh và AI đều lỗi). "
    "Anh/chị có thể bấm Đăng để đăng không ảnh, hoặc góp ý."
)


class ImagePlan(BaseModel):
    kind: Literal["stock", "ai"]
    stock_query: str
    ai_prompt: str


@dataclass
class ImageResult:
    paths: list[str] = field(default_factory=list)
    note: str = ""


def _new_path(dest_dir: Path, suffix: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    return (dest_dir / f"{uuid4().hex}{suffix}").resolve()


def _log_failure(what: str, exc: Exception) -> None:
    # Type and HTTP status only: never headers, URLs with keys, or messages.
    status = None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    log.warning("%s failed: %s status=%s", what, type(exc).__name__, status)


def fetch_stock(query: str, dest_dir: Path, settings: Settings) -> ImageResult | None:
    if not settings.UNSPLASH_ACCESS_KEY:
        return None
    auth = {"Authorization": f"Client-ID {settings.UNSPLASH_ACCESS_KEY}", "Accept-Version": "v1"}
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(
                UNSPLASH_SEARCH_URL,
                params={
                    "query": query,
                    "per_page": 5,
                    "orientation": "landscape",
                    "content_filter": "high",
                },
                headers=auth,
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
            if not results:
                return None
            photo = results[0]
            img = client.get(photo["urls"]["regular"])
            img.raise_for_status()
            _track_download(client, photo, auth)
        path = _new_path(dest_dir, ".jpg")
        path.write_bytes(img.content)
        author = (photo.get("user") or {}).get("name") or "Unsplash"
        return ImageResult(paths=[str(path)], note=f"Ảnh: {author} / Unsplash")
    except Exception as exc:  # noqa: BLE001 - never raise to the scheduler
        _log_failure("unsplash", exc)
        return None


def _track_download(client: httpx.Client, photo: dict[str, Any], auth: dict[str, str]) -> None:
    """Unsplash API guidelines require hitting download_location when a photo is used."""
    url = (photo.get("links") or {}).get("download_location")
    if not url:
        return
    try:
        client.get(url, headers=auth).raise_for_status()
    except Exception as exc:  # noqa: BLE001 - tracking must not cost us the photo
        _log_failure("unsplash download tracking", exc)


def generate_ai(prompt: str, dest_dir: Path, settings: Settings) -> ImageResult | None:
    if not settings.GEMINI_API_KEY:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=settings.GEMINI_IMAGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        for candidate in response.candidates or []:
            parts = candidate.content.parts if candidate.content else None
            for part in parts or []:
                data = part.inline_data.data if part.inline_data else None
                if data:
                    path = _new_path(dest_dir, ".png")
                    path.write_bytes(data)
                    return ImageResult(
                        paths=[str(path)], note="Ảnh minh họa do AI (Gemini) tạo"
                    )
        log.warning("gemini returned no image")
        return None
    except Exception as exc:  # noqa: BLE001
        _log_failure("gemini", exc)
        return None


def get_morning_image(plan: ImagePlan, dest_dir: Path, settings: Settings) -> ImageResult:
    """Try the planned source first, then the other. Never raises."""
    attempts: list[Callable[[], ImageResult | None]] = [
        lambda: fetch_stock(plan.stock_query, dest_dir, settings),
        lambda: generate_ai(plan.ai_prompt, dest_dir, settings),
    ]
    if plan.kind == "ai":
        attempts.reverse()
    for attempt in attempts:
        try:
            result = attempt()
        except Exception as exc:  # noqa: BLE001 - try the other source
            _log_failure("morning image", exc)
            continue
        if result is not None:
            return result
    return ImageResult(paths=[], note=NO_IMAGE_NOTE)
