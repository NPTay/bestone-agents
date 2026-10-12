import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from app.config import get_settings

POST_NEW = {"cta", "alt_opening", "sensitive_reasons", "rejection_reason", "planned_for",
            "research_item_id"}  # fmt: skip
RESEARCH_NEW = {"angle_suggestion", "score_reasons", "risk_flags", "published_at"}


@pytest.fixture
def db(tmp_path, monkeypatch) -> Iterator[tuple[Config, str]]:  # type: ignore[no-untyped-def]
    url = f"sqlite:///{tmp_path / 'm2.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        yield Config("alembic.ini"), url
    finally:
        get_settings.cache_clear()


def _cols(url: str, table: str) -> set[str]:
    eng = sa.create_engine(url)
    try:
        return {c["name"] for c in sa.inspect(eng).get_columns(table)}
    finally:
        eng.dispose()


def _insert_post(conn: sa.Connection, planned: date | None, pillar: str | None) -> None:
    now = datetime.now(UTC)
    conn.execute(
        sa.text(
            "insert into posts (id, pillar, body, hashtags, sources, kb_refs, status, sensitive,"
            " sensitive_reasons, planned_for, created_at, updated_at) values"
            " (:id, :pillar, '', '[]', '[]', '[]', 'draft', 0, '[]', :planned, :now, :now)"
        ),
        {"id": uuid.uuid4().hex, "pillar": pillar, "planned": planned, "now": now},
    )


def test_upgrade_adds_columns_and_no_drift(db) -> None:  # type: ignore[no-untyped-def]
    cfg, url = db
    command.upgrade(cfg, "head")
    command.check(cfg)
    assert POST_NEW <= _cols(url, "posts")
    assert RESEARCH_NEW <= _cols(url, "research_items")
    eng = sa.create_engine(url)
    insp = sa.inspect(eng)
    uniques = {u["name"]: u["column_names"] for u in insp.get_unique_constraints("posts")}
    assert uniques["uq_posts_planned_pillar"] == ["planned_for", "pillar"]
    fks = {
        tuple(f["constrained_columns"]): f["referred_table"] for f in insp.get_foreign_keys("posts")
    }
    assert fks[("research_item_id",)] == "research_items"
    eng.dispose()


def test_duplicate_planned_slot_rejected(db) -> None:  # type: ignore[no-untyped-def]
    cfg, url = db
    command.upgrade(cfg, "head")
    eng = sa.create_engine(url)
    with eng.begin() as conn:
        _insert_post(conn, date(2026, 10, 12), "Tin ngành & tương tác")
        _insert_post(conn, date(2026, 10, 13), "Tin ngành & tương tác")
        _insert_post(conn, None, None)  # NULLs never collide
        _insert_post(conn, None, None)
    with pytest.raises(IntegrityError), eng.begin() as conn:
        _insert_post(conn, date(2026, 10, 12), "Tin ngành & tương tác")
    eng.dispose()


def test_rejected_status_accepted(db) -> None:  # type: ignore[no-untyped-def]
    from app.db.models import POST_STATUSES

    assert "rejected" in POST_STATUSES


def test_round_trip_downgrade_0001(db) -> None:  # type: ignore[no-untyped-def]
    cfg, url = db
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")
    assert not (POST_NEW & _cols(url, "posts"))
    assert not (RESEARCH_NEW & _cols(url, "research_items"))
    eng = sa.create_engine(url)
    assert "uq_posts_planned_pillar" not in {
        u["name"] for u in sa.inspect(eng).get_unique_constraints("posts")
    }
    eng.dispose()
    command.upgrade(cfg, "head")
    command.check(cfg)
    assert POST_NEW <= _cols(url, "posts")
