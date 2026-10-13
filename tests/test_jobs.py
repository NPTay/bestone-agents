import uuid
from collections.abc import Callable

from sqlalchemy import orm, select

from app.db.models import Alert, Job
from app.jobs import run_job
from app.llm.client import LLMError


def _jobs(db_factory: Callable[[], orm.Session]) -> list[Job]:
    with db_factory() as s:
        return list(s.scalars(select(Job).order_by(Job.created_at)))


def test_run_job_retries_then_succeeds(db_factory: Callable[[], orm.Session]) -> None:
    calls: list[uuid.UUID] = []
    sleeps: list[float] = []

    def fn(db: orm.Session, job_id: uuid.UUID) -> str:
        calls.append(job_id)
        with db_factory() as other:
            running = other.get(Job, job_id)
            assert running is not None and running.status == "running"
        if len(calls) < 3:
            raise RuntimeError("boom")
        return "ok"

    result = run_job(
        db_factory, agent="research", kind="a1_daily", payload={}, fn=fn, sleep=sleeps.append
    )
    assert result == "ok"
    (job,) = _jobs(db_factory)
    assert job.status == "done" and job.attempts == 3
    assert job.finished_at is not None and job.started_at is not None
    assert sleeps == [2.0, 4.0]
    assert len(set(calls)) == 1


def test_run_job_fails_and_alerts(db_factory: Callable[[], orm.Session]) -> None:
    def fn(db: orm.Session, job_id: uuid.UUID) -> str:
        raise RuntimeError("boom")

    result = run_job(
        db_factory,
        agent="research",
        kind="a1_daily",
        payload={"k": "v"},
        fn=fn,
        sleep=lambda s: None,
    )
    assert result is None
    (job,) = _jobs(db_factory)
    assert job.status == "failed" and job.attempts == 3
    assert job.error == "RuntimeError: boom"
    with db_factory() as s:
        (alert,) = s.scalars(select(Alert)).all()
    assert alert.level == "warn"
    assert "a1_daily" in alert.message and "3 lần" in alert.message


def test_three_consecutive_failures_urgent(db_factory: Callable[[], orm.Session]) -> None:
    def fn(db: orm.Session, job_id: uuid.UUID) -> str:
        raise RuntimeError("boom")

    for _ in range(3):
        run_job(
            db_factory,
            agent="research",
            kind="a1_daily",
            payload={},
            fn=fn,
            max_attempts=1,
            sleep=lambda s: None,
        )
    with db_factory() as s:
        levels = [a.level for a in s.scalars(select(Alert).order_by(Alert.created_at))]
    assert levels[-1] == "urgent"
    assert "urgent" not in levels[:2]


def test_llm_error_text_and_truncation(db_factory: Callable[[], orm.Session]) -> None:
    def fn(db: orm.Session, job_id: uuid.UUID) -> str:
        raise LLMError("refusal", "secret detail")

    run_job(
        db_factory, agent="a", kind="k", payload={}, fn=fn, max_attempts=1, sleep=lambda s: None
    )
    assert _jobs(db_factory)[0].error == "LLMError(refusal)"

    def long_fn(db: orm.Session, job_id: uuid.UUID) -> str:
        raise ValueError("x" * 5000)

    run_job(
        db_factory,
        agent="a",
        kind="k2",
        payload={},
        fn=long_fn,
        max_attempts=1,
        sleep=lambda s: None,
    )
    err = [j for j in _jobs(db_factory) if j.kind == "k2"][0].error
    assert err is not None and len(err) == 2000


def test_alert_on_failure_false_skips_alerts_but_records_failure(
    db_factory: Callable[[], orm.Session],
) -> None:
    def fn(db: orm.Session, job_id: uuid.UUID) -> str:
        raise RuntimeError("boom")

    for _ in range(3):  # would otherwise reach the urgent streak too
        result = run_job(
            db_factory,
            agent="content",
            kind="draft_morning",
            payload={},
            fn=fn,
            max_attempts=1,
            sleep=lambda s: None,
            alert_on_failure=False,
        )
        assert result is None
    jobs = _jobs(db_factory)
    assert [j.status for j in jobs] == ["failed"] * 3
    assert all(j.error == "RuntimeError: boom" for j in jobs)
    with db_factory() as s:
        assert s.scalars(select(Alert)).all() == []
