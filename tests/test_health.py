from fastapi.testclient import TestClient
from pytest import MonkeyPatch


def test_health_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}


def test_health_db_down(client: TestClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("app.routers.health.check_db", lambda db: False)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "error", "db": "error"}
