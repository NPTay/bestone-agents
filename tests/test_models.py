from pathlib import Path

import pytest
from sqlalchemy import inspect

from app.db.base import Base
from app.db.init import init_db
from app.db.session import make_engine


def test_init_db_creates_tables_and_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    try:
        init_db(engine)
        tables = set(inspect(engine).get_table_names())
        assert {"jobs", "alerts", "llm_usage", "settings"} <= tables
        assert (data_dir / "media").is_dir()
        assert (data_dir / "logs").is_dir()
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_only_core_tables_defined() -> None:
    assert set(Base.metadata.tables) == {"jobs", "alerts", "llm_usage", "settings"}
