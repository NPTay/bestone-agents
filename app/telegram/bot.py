import json
import logging
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx

MAX_PHOTOS = 10
ALLOWED_UPDATES = ["message", "callback_query"]

# httpx logs full request URLs at INFO, and the Telegram URL embeds the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)


class TelegramError(Exception):
    """Telegram API failure. The message never contains the bot token or the URL."""


class TelegramBot:
    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None) -> None:
        self._token = token
        self._chat_id = chat_id
        self._client = client or httpx.Client(timeout=40)

    def _call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: list[tuple[str, Any]] | None = None,
    ) -> Any:
        url = f"https://api.telegram.org/bot{self._token}/{method}"
        try:
            if files is not None:
                resp = self._client.post(url, data=data, files=files)
            else:
                resp = self._client.post(url, json=payload)
        except httpx.HTTPError as exc:
            # Only the type name: httpx messages can embed the URL (and the token).
            raise TelegramError(f"{method} failed: {type(exc).__name__}") from None
        try:
            body = resp.json()
        except ValueError:
            body = None
        if resp.status_code >= 400 or not isinstance(body, dict) or not body.get("ok"):
            desc = body.get("description") if isinstance(body, dict) else None
            raise TelegramError(
                f"{method} failed: {desc or 'HTTP ' + str(resp.status_code)}"
            ) from None
        return body.get("result")

    def send_message(
        self,
        text: str,
        buttons: list[tuple[str, str]] | None = None,
        reply_to: int | None = None,
    ) -> int:
        payload: dict[str, Any] = {"chat_id": self._chat_id, "text": text}
        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]
            }
        if reply_to is not None:
            payload["reply_parameters"] = {"message_id": reply_to}
        result = self._call("sendMessage", payload)
        if not isinstance(result, dict) or "message_id" not in result:
            raise TelegramError("sendMessage failed: no message_id in response")
        return int(result["message_id"])

    def send_photos(self, paths: list[str]) -> None:
        paths = paths[:MAX_PHOTOS]
        if not paths:
            return
        with ExitStack() as stack:
            handles = [stack.enter_context(open(p, "rb")) for p in paths]
            if len(handles) == 1:
                self._call(
                    "sendPhoto",
                    data={"chat_id": self._chat_id},
                    files=[("photo", (Path(paths[0]).name, handles[0]))],
                )
                return
            media = [{"type": "photo", "media": f"attach://photo{i}"} for i in range(len(handles))]
            files = [
                (f"photo{i}", (Path(p).name, h))
                for i, (p, h) in enumerate(zip(paths, handles, strict=True))
            ]
            self._call(
                "sendMediaGroup",
                data={"chat_id": self._chat_id, "media": json.dumps(media)},
                files=files,
            )

    def answer_callback(self, callback_id: str, text: str) -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def edit_buttons_removed(self, message_id: int) -> None:
        self._call(
            "editMessageReplyMarkup",
            {
                "chat_id": self._chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": []},
            },
        )

    def get_updates(self, offset: int, timeout: int = 30) -> list[dict[str, Any]]:
        result = self._call(
            "getUpdates",
            {"offset": offset, "timeout": timeout, "allowed_updates": ALLOWED_UPDATES},
        )
        return list(result)


class FakeTelegram:
    """In-memory stand-in for TelegramBot, used by tests."""

    def __init__(self, chat_id: str = "1") -> None:
        self.chat_id = chat_id
        self.sent: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self._next_id = 100

    def send_message(
        self,
        text: str,
        buttons: list[tuple[str, str]] | None = None,
        reply_to: int | None = None,
    ) -> int:
        message_id = self._next_id
        self._next_id += 1
        self.sent.append(
            {
                "method": "send_message",
                "text": text,
                "buttons": buttons,
                "reply_to": reply_to,
                "message_id": message_id,
            }
        )
        return message_id

    def send_photos(self, paths: list[str]) -> None:
        self.sent.append({"method": "send_photos", "paths": list(paths)})

    def answer_callback(self, callback_id: str, text: str) -> None:
        self.sent.append({"method": "answer_callback", "callback_id": callback_id, "text": text})

    def edit_buttons_removed(self, message_id: int) -> None:
        self.sent.append({"method": "edit_buttons_removed", "message_id": message_id})

    def get_updates(self, offset: int, timeout: int = 30) -> list[dict[str, Any]]:
        return [u for u in self.updates if u["update_id"] >= offset]
