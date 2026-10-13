from pathlib import Path

from sqlalchemy import text

from app.db.session import make_engine


def test_file_sqlite_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    try:
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 30000
    finally:
        engine.dispose()


def test_in_memory_sqlite_is_unchanged() -> None:
    engine = make_engine("sqlite://")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "memory"
    engine.dispose()
