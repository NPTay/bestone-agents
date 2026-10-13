"""Minimal Facebook Graph API client for publishing to the Page."""

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings


class GraphError(Exception):
    """Graph API failure. The message never contains the access token."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class GraphClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._page_id = settings.META_PAGE_ID
        self._token = settings.META_PAGE_ACCESS_TOKEN
        self._base = f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}"
        self._client = client or httpx.Client(timeout=60)

    def _scrub(self, text: str) -> str:
        return text.replace(self._token, "***") if self._token else text

    def _request(
        self,
        path: str,
        data: dict[str, str] | None = None,
        files: list[tuple[str, Any]] | None = None,
    ) -> dict[str, Any]:
        form = dict(data or {})
        form["access_token"] = self._token
        url = f"{self._base}/{path}"
        try:
            if files is not None:
                resp = self._client.post(url, data=form, files=files)
            else:
                resp = self._client.post(url, data=form)
        except httpx.HTTPError as exc:
            # Only the type name: httpx messages can embed the URL.
            raise GraphError(-1, type(exc).__name__) from None
        try:
            body = resp.json()
        except ValueError:
            body = None
        self._raise_if_error(body)
        if resp.status_code >= 400 or not isinstance(body, dict):
            raise GraphError(-1, f"HTTP {resp.status_code}") from None
        return body

    def _raise_if_error(self, body: Any) -> None:
        """Raise GraphError when `body` is a Graph error payload (token scrubbed)."""
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            err = body["error"]
            code = err.get("code")
            raise GraphError(
                code if isinstance(code, int) else -1,
                self._scrub(str(err.get("message", "Unknown error"))),
            ) from None

    def _upload_photo(self, path: str, data: dict[str, str]) -> dict[str, Any]:
        with ExitStack() as stack:
            handle = stack.enter_context(open(path, "rb"))
            return self._request(
                f"{self._page_id}/photos",
                data=data,
                files=[("source", (Path(path).name, handle))],
            )

    def publish(self, message: str, image_paths: list[str]) -> str:
        """Publish to the Page feed and return the Facebook post id."""
        if not image_paths:
            body = self._request(f"{self._page_id}/feed", data={"message": message})
            return _require_id(body, "id")
        if len(image_paths) == 1:
            body = self._upload_photo(image_paths[0], {"message": message})
            return _require_id(body, "post_id", "id")
        form: dict[str, str] = {"message": message}
        for i, path in enumerate(image_paths):
            uploaded = self._upload_photo(path, {"published": "false"})
            form[f"attached_media[{i}]"] = json.dumps({"media_fbid": _require_id(uploaded, "id")})
        body = self._request(f"{self._page_id}/feed", data=form)
        return _require_id(body, "id")

    def comment(self, post_id: str, text: str) -> str:
        body = self._request(f"{post_id}/comments", data={"message": text})
        return _require_id(body, "id")

    def page_name(self) -> str:
        # GET: the token goes in a header so it never appears in the URL.
        url = f"{self._base}/{self._page_id}"
        try:
            resp = self._client.get(url, params={"fields": "name"}, headers=self._auth_header())
            body = resp.json()
        except httpx.HTTPError as exc:
            raise GraphError(-1, type(exc).__name__) from None
        except ValueError:
            raise GraphError(-1, "Invalid response") from None
        self._raise_if_error(body)
        if resp.status_code >= 400 or not isinstance(body, dict) or "name" not in body:
            raise GraphError(-1, f"HTTP {resp.status_code}") from None
        return str(body["name"])

    def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}


def _require_id(body: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = body.get(key)
        if value:
            return str(value)
    raise GraphError(-1, "Missing id in response")
