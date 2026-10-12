import pytest

from tests.conftest import _assert_test_database


def test_guard_accepts_test_database() -> None:
    _assert_test_database("postgresql+psycopg://test:test@localhost:5433/bestone_test")


def test_guard_rejects_production_like_database() -> None:
    with pytest.raises(pytest.exit.Exception) as exc:
        _assert_test_database("postgresql+psycopg://bestone_app:pw@db:5432/bestone")
    assert exc.value.returncode == 2
