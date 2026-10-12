from fastapi import APIRouter, Depends, Request, Response
from fastapi.testclient import TestClient

from app.auth.csrf import CSRF_COOKIE, ensure_csrf_cookie, verify_csrf


def _mount(client: TestClient) -> None:
    router = APIRouter()

    @router.get("/_form")
    def form(request: Request, response: Response) -> dict[str, str]:
        return {"token": ensure_csrf_cookie(request, response)}

    @router.post("/_submit", dependencies=[Depends(verify_csrf)])
    def submit() -> dict[str, bool]:
        return {"ok": True}

    client.app.include_router(router)  # type: ignore[attr-defined]


def test_missing_cookie_and_token_403(client: TestClient) -> None:
    _mount(client)
    assert client.post("/_submit", data={}).status_code == 403


def test_missing_token_403(client: TestClient) -> None:
    _mount(client)
    client.get("/_form")
    assert client.post("/_submit", data={}).status_code == 403


def test_wrong_token_403(client: TestClient) -> None:
    _mount(client)
    client.get("/_form")
    assert client.post("/_submit", data={"csrf_token": "bad"}).status_code == 403


def test_valid_token_200(client: TestClient) -> None:
    _mount(client)
    token = client.get("/_form").json()["token"]
    assert client.post("/_submit", data={"csrf_token": token}).status_code == 200


def test_cookie_reused_and_flags(client: TestClient) -> None:
    _mount(client)
    r = client.get("/_form")
    sc = r.headers["set-cookie"].lower()
    assert CSRF_COOKIE in sc and "httponly" in sc and "samesite=lax" in sc
    first = r.json()["token"]
    assert client.get("/_form").json()["token"] == first


def test_token_from_other_cookie_rejected(client: TestClient) -> None:
    _mount(client)
    token = client.get("/_form").json()["token"]
    client.cookies.set(CSRF_COOKIE, "attacker-chosen")
    assert client.post("/_submit", data={"csrf_token": token}).status_code == 403
