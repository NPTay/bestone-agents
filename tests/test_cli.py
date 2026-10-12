from datetime import timedelta

import pytest
from sqlalchemy import Engine, orm

from app.auth.passwords import verify_password
from app.cli import create_admin, reset_password
from app.clock import utcnow
from app.db.models import AuditLog, Role, User, UserSession


def _session(engine: Engine) -> orm.Session:
    return orm.sessionmaker(bind=engine, expire_on_commit=False)()


def test_create_admin_once(
    db_url_env: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("INITIAL_ADMIN_USERNAME", "giamdoc")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "Matkhau#2026")
    assert create_admin.main([]) == 0
    assert create_admin.main([]) == 1
    with _session(db_url_env) as s:
        users = s.query(User).all()
        assert len(users) == 1 and users[0].role == Role.giam_doc
        assert verify_password(users[0].password_hash, "Matkhau#2026")
    assert "Matkhau#2026" not in capsys.readouterr().out


def test_create_admin_requires_env(db_url_env: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INITIAL_ADMIN_USERNAME", "giamdoc")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "")
    assert create_admin.main([]) == 1
    monkeypatch.setenv("INITIAL_ADMIN_USERNAME", "")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "Matkhau#2026")
    assert create_admin.main([]) == 1


def test_create_admin_rejects_short_password(
    db_url_env: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INITIAL_ADMIN_USERNAME", "giamdoc")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "ngan")
    assert create_admin.main([]) == 1
    with _session(db_url_env) as s:
        assert s.query(User).count() == 0


def test_reset_password_unlocks_and_kills_sessions(
    db_url_env: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _session(db_url_env)
    from app.auth.passwords import hash_password

    u = User(username="gd", password_hash=hash_password("Cu#12345678"), role=Role.giam_doc)
    db.add(u)
    db.commit()
    u.failed_attempts = 5
    u.last_failed_at = utcnow()
    u.locked_until = utcnow() + timedelta(minutes=10)
    db.add(
        UserSession(
            user_id=u.id,
            token_hash="h",
            expires_at=utcnow() + timedelta(hours=1),
            last_seen_at=utcnow(),
        )
    )
    db.commit()
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "Matkhaumoi#2026")
    assert reset_password.main(["--username", u.username]) == 0
    db.refresh(u)
    assert u.failed_attempts == 0 and u.locked_until is None and u.last_failed_at is None
    assert verify_password(u.password_hash, "Matkhaumoi#2026")
    assert db.query(UserSession).filter_by(user_id=u.id).count() == 0
    assert db.query(AuditLog).filter_by(action="password_reset_cli").count() == 1
    db.close()


def test_reset_password_mismatch_changes_nothing(
    db_url_env: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter(["Matkhaumoi#2026", "Khac#20269999"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    with _session(db_url_env) as s:
        s.add(User(username="gd", password_hash="old", role=Role.giam_doc))
        s.commit()
    assert reset_password.main(["--username", "gd"]) == 1
    with _session(db_url_env) as s:
        assert s.query(User).one().password_hash == "old"


def test_reset_password_unknown_user_and_short(
    db_url_env: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "Matkhaumoi#2026")
    assert reset_password.main(["--username", "nobody"]) == 1
    with _session(db_url_env) as s:
        s.add(User(username="gd", password_hash="old", role=Role.giam_doc))
        s.commit()
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "ngan")
    assert reset_password.main(["--username", "gd"]) == 1
    with _session(db_url_env) as s:
        assert s.query(User).one().password_hash == "old"
