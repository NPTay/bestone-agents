from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.meta.graph import NOT_SENT, GraphClient, GraphError

BASE = "https://graph.facebook.com/v26.0"
TOKEN = "SECRET_TOKEN_XYZ"


@pytest.fixture
def graph() -> GraphClient:
    settings = Settings(
        META_PAGE_ID="123", META_PAGE_ACCESS_TOKEN=TOKEN, META_GRAPH_VERSION="v26.0"
    )
    return GraphClient(settings)


@pytest.fixture
def images(tmp_path: Path) -> list[str]:
    out = []
    for name in ("a.jpg", "b.jpg"):
        p = tmp_path / name
        p.write_bytes(b"\xff\xd8fake")
        out.append(str(p))
    return out


def test_publish_text_only_uses_feed(graph: GraphClient, respx_mock) -> None:  # type: ignore[no-untyped-def]
    route = respx_mock.post(f"{BASE}/123/feed").respond(200, json={"id": "123_9"})
    assert graph.publish("hi", []) == "123_9"
    req = route.calls.last.request
    assert TOKEN not in str(req.url)
    assert b"access_token=" + TOKEN.encode() in req.content


def test_publish_single_photo_uses_photos_endpoint(
    graph: GraphClient,
    images: list[str],
    respx_mock,  # type: ignore[no-untyped-def]
) -> None:
    route = respx_mock.post(f"{BASE}/123/photos").respond(
        200, json={"id": "photo1", "post_id": "123_77"}
    )
    assert graph.publish("hello", images[:1]) == "123_77"
    req = route.calls.last.request
    assert TOKEN not in str(req.url)
    assert b'name="source"' in req.content and b'name="message"' in req.content
    assert b"hello" in req.content


def test_publish_multiple_photos_attaches_media(
    graph: GraphClient,
    images: list[str],
    respx_mock,  # type: ignore[no-untyped-def]
) -> None:
    photos = respx_mock.post(f"{BASE}/123/photos").mock(
        side_effect=[httpx.Response(200, json={"id": "m1"}), httpx.Response(200, json={"id": "m2"})]
    )
    feed = respx_mock.post(f"{BASE}/123/feed").respond(200, json={"id": "123_5"})
    assert graph.publish("msg", images) == "123_5"
    assert photos.call_count == 2
    for call in photos.calls:
        assert b"published" in call.request.content and b"false" in call.request.content
    body = feed.calls.last.request.content.decode()
    assert "attached_media%5B0%5D" in body and "m1" in body
    assert "attached_media%5B1%5D" in body and "m2" in body


def test_comment_posts_to_post_comments(graph: GraphClient, respx_mock) -> None:  # type: ignore[no-untyped-def]
    route = respx_mock.post(f"{BASE}/123_5/comments").respond(200, json={"id": "c1"})
    assert graph.comment("123_5", "text") == "c1"
    assert route.called


def test_page_name_keeps_token_out_of_url(graph: GraphClient, respx_mock) -> None:  # type: ignore[no-untyped-def]
    route = respx_mock.get(url__regex=r"https://graph\.facebook\.com/v26\.0/123.*").respond(
        200, json={"name": "Bestone", "id": "123"}
    )
    assert graph.page_name() == "Bestone"
    assert TOKEN not in str(route.calls.last.request.url)


def test_graph_error_hides_token(graph: GraphClient, respx_mock) -> None:  # type: ignore[no-untyped-def]
    respx_mock.post(f"{BASE}/123/feed").respond(
        400, json={"error": {"code": 190, "message": f"Invalid token {TOKEN} here"}}
    )
    with pytest.raises(GraphError) as info:
        graph.publish("x", [])
    assert info.value.code == 190
    assert TOKEN not in info.value.message and TOKEN not in str(info.value)


def test_network_and_non_json_errors(graph: GraphClient, respx_mock) -> None:  # type: ignore[no-untyped-def]
    respx_mock.post(f"{BASE}/123/feed").mock(side_effect=httpx.ReadTimeout(f"boom {TOKEN}"))
    with pytest.raises(GraphError) as info:
        graph.publish("x", [])
    assert info.value.code == -1 and TOKEN not in info.value.message
    respx_mock.post(f"{BASE}/123/feed").respond(502, text="<html>bad gateway</html>")
    with pytest.raises(GraphError) as info2:
        graph.publish("x", [])
    assert info2.value.code == -1 and "502" in info2.value.message


@pytest.mark.parametrize("exc", [httpx.ConnectError("x"), httpx.ConnectTimeout("x")])
def test_connect_failure_means_not_sent(
    graph: GraphClient,
    respx_mock,  # type: ignore[no-untyped-def]
    exc: Exception,
) -> None:
    respx_mock.post(f"{BASE}/123/feed").mock(side_effect=exc)
    with pytest.raises(GraphError) as info:
        graph.publish("hi", [])
    assert info.value.code == NOT_SENT == -2
    assert TOKEN not in info.value.message


@pytest.mark.parametrize(
    "exc", [httpx.ReadTimeout("x"), httpx.WriteError("x"), httpx.RemoteProtocolError("x")]
)
def test_ambiguous_transport_failure_stays_minus_one(
    graph: GraphClient,
    respx_mock,  # type: ignore[no-untyped-def]
    exc: Exception,
) -> None:
    respx_mock.post(f"{BASE}/123/feed").mock(side_effect=exc)
    with pytest.raises(GraphError) as info:
        graph.publish("hi", [])
    assert info.value.code == -1


def test_token_owner_id_reads_me_with_header(graph: GraphClient, respx_mock) -> None:  # type: ignore[no-untyped-def]
    route = respx_mock.get(url__regex=r"https://graph\.facebook\.com/v26\.0/me.*").respond(
        200, json={"id": "999"}
    )
    assert graph.token_owner_id() == "999"
    req = route.calls.last.request
    assert TOKEN not in str(req.url)
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"


def test_token_owner_id_error_hides_token(graph: GraphClient, respx_mock) -> None:  # type: ignore[no-untyped-def]
    respx_mock.get(url__regex=r"https://graph\.facebook\.com/v26\.0/me.*").respond(
        400, json={"error": {"code": 190, "message": f"bad {TOKEN}"}}
    )
    with pytest.raises(GraphError) as info:
        graph.token_owner_id()
    assert TOKEN not in info.value.message
