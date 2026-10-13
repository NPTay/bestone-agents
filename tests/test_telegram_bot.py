import json
from pathlib import Path

import httpx
import pytest

from app.telegram.bot import FakeTelegram, TelegramBot, TelegramError

TOKEN = "123:SECRET"
BASE = rf"https://api\.telegram\.org/bot{TOKEN}/"


def _bot() -> TelegramBot:
    return TelegramBot(TOKEN, "42")


def test_send_message_posts_inline_keyboard(respx_mock) -> None:  # type: ignore[no-untyped-def]
    route = respx_mock.post(url__regex=BASE + "sendMessage").respond(
        200, json={"ok": True, "result": {"message_id": 77}}
    )
    mid = _bot().send_message("hi", buttons=[("OK", "ok:1:1"), ("No", "no:1:1")], reply_to=5)
    assert mid == 77
    payload = json.loads(route.calls[0].request.content)
    assert payload["chat_id"] == "42"
    assert payload["reply_markup"]["inline_keyboard"] == [
        [{"text": "OK", "callback_data": "ok:1:1"}, {"text": "No", "callback_data": "no:1:1"}]
    ]
    assert payload["reply_parameters"] == {"message_id": 5}


def test_send_message_without_buttons_has_no_markup(respx_mock) -> None:  # type: ignore[no-untyped-def]
    route = respx_mock.post(url__regex=BASE + "sendMessage").respond(
        200, json={"ok": True, "result": {"message_id": 1}}
    )
    _bot().send_message("hi")
    payload = json.loads(route.calls[0].request.content)
    assert "reply_markup" not in payload and "reply_parameters" not in payload


def test_error_message_hides_token(respx_mock) -> None:  # type: ignore[no-untyped-def]
    respx_mock.post(url__regex=BASE + "sendMessage").respond(
        400, json={"ok": False, "description": "Bad Request: chat not found"}
    )
    with pytest.raises(TelegramError) as info:
        _bot().send_message("hi")
    assert "chat not found" in str(info.value)
    assert TOKEN not in str(info.value) and "SECRET" not in str(info.value)


def test_network_error_hides_token(respx_mock) -> None:  # type: ignore[no-untyped-def]
    respx_mock.post(url__regex=BASE + "sendMessage").mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(TelegramError) as info:
        _bot().send_message("hi")
    assert "ConnectError" in str(info.value)
    assert "SECRET" not in str(info.value)


def _images(tmp_path: Path, n: int) -> list[str]:
    paths = []
    for i in range(n):
        p = tmp_path / f"img{i}.jpg"
        p.write_bytes(b"x" * (i + 1))
        paths.append(str(p))
    return paths


def test_send_photos_single_uses_send_photo(respx_mock, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    route = respx_mock.post(url__regex=BASE + "sendPhoto").respond(
        200, json={"ok": True, "result": {}}
    )
    _bot().send_photos(_images(tmp_path, 1))
    assert route.called


def test_send_photos_uses_media_group_for_three(respx_mock, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    route = respx_mock.post(url__regex=BASE + "sendMediaGroup").respond(
        200, json={"ok": True, "result": []}
    )
    _bot().send_photos(_images(tmp_path, 3))
    body = route.calls[0].request.content
    assert b'name="photo0"' in body and b'name="photo2"' in body
    assert b"attach://photo0" in body and b"attach://photo2" in body


def test_send_photos_caps_at_ten_and_skips_empty(respx_mock, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    route = respx_mock.post(url__regex=BASE + "sendMediaGroup").respond(
        200, json={"ok": True, "result": []}
    )
    bot = _bot()
    bot.send_photos(_images(tmp_path, 12))
    body = route.calls[0].request.content
    assert b'name="photo9"' in body and b'name="photo10"' not in body
    bot.send_photos([])
    assert route.call_count == 1


def test_other_methods(respx_mock) -> None:  # type: ignore[no-untyped-def]
    ans = respx_mock.post(url__regex=BASE + "answerCallbackQuery").respond(
        200, json={"ok": True, "result": True}
    )
    edit = respx_mock.post(url__regex=BASE + "editMessageReplyMarkup").respond(
        200, json={"ok": True, "result": True}
    )
    upd = respx_mock.post(url__regex=BASE + "getUpdates").respond(
        200, json={"ok": True, "result": [{"update_id": 3}]}
    )
    bot = _bot()
    bot.answer_callback("cb1", "xong")
    bot.edit_buttons_removed(9)
    assert bot.get_updates(3, timeout=0) == [{"update_id": 3}]
    assert json.loads(ans.calls[0].request.content) == {
        "callback_query_id": "cb1",
        "text": "xong",
    }
    assert json.loads(edit.calls[0].request.content)["reply_markup"] == {"inline_keyboard": []}
    sent = json.loads(upd.calls[0].request.content)
    assert sent["offset"] == 3 and sent["allowed_updates"] == ["message", "callback_query"]


def test_fake_telegram_records_and_serves_updates() -> None:
    fake = FakeTelegram()
    assert fake.send_message("a") == 100
    assert fake.send_message("b", buttons=[("x", "y")], reply_to=100) == 101
    fake.send_photos(["/a.jpg"])
    fake.answer_callback("c", "t")
    fake.edit_buttons_removed(100)
    assert [s["method"] for s in fake.sent] == [
        "send_message",
        "send_message",
        "send_photos",
        "answer_callback",
        "edit_buttons_removed",
    ]
    fake.updates = [{"update_id": 1}, {"update_id": 2}]
    assert fake.get_updates(2, 0) == [{"update_id": 2}]
