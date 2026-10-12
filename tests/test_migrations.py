import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import get_settings
from tests.test_models import EXPECTED


def test_upgrade_head_matches_models(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    url = f"sqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")
        command.check(cfg)  # no drift between models and migration
        eng = sa.create_engine(url)
        assert EXPECTED <= set(sa.inspect(eng).get_table_names())
        with eng.connect() as c:
            rows = dict(c.execute(sa.text("select key, value from settings")).all())
        assert rows == {"AUTONOMY_LEVEL": "draft_only", "KILL_SWITCH": "false"}
        eng.dispose()
    finally:
        get_settings.cache_clear()
