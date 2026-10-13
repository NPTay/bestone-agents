import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import orm, select

from app import clock
from app.db.models import Job
from app.integrations.notify import send_alert
from app.llm.client import LLMError

logger = logging.getLogger(__name__)

MAX_ERROR_LEN = 2000
URGENT_STREAK = 3


def _error_text(exc: Exception) -> str:
    if isinstance(exc, LLMError):
        return f"LLMError({exc.reason})"
    return f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LEN]


def _update_job(db_factory: Callable[[], orm.Session], job_id: uuid.UUID, **fields: Any) -> None:
    with db_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        for name, value in fields.items():
            setattr(job, name, value)
        db.commit()


def _recent_all_failed(db: orm.Session, kind: str) -> bool:
    statuses = db.scalars(
        select(Job.status)
        .where(Job.kind == kind)
        .order_by(Job.created_at.desc())
        .limit(URGENT_STREAK)
    ).all()
    return len(statuses) == URGENT_STREAK and all(s == "failed" for s in statuses)


def run_job[T](
    db_factory: Callable[[], orm.Session],
    *,
    agent: str,
    kind: str,
    payload: dict[str, Any],
    fn: Callable[[orm.Session, uuid.UUID], T],
    max_attempts: int = 3,
    backoff_base_s: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    alert_on_failure: bool = True,
) -> T | None:
    """Run fn with bounded retries, recording the outcome in the jobs table.

    Returns fn's result, or None after the final failed attempt (never raises).
    ``alert_on_failure=False`` skips the failure alerts (the caller owns them);
    the job is still recorded as failed and logged.
    """
    with db_factory() as db:
        job = Job(
            agent=agent,
            kind=kind,
            payload=payload,
            status="running",
            attempts=0,
            started_at=clock.utcnow(),
        )
        db.add(job)
        db.commit()
        job_id = job.id

    last_error = ""
    for attempt in range(1, max_attempts + 1):
        _update_job(db_factory, job_id, attempts=attempt)
        try:
            with db_factory() as work_db:
                try:
                    result = fn(work_db, job_id)
                except Exception:
                    work_db.rollback()
                    raise
        except Exception as exc:
            last_error = _error_text(exc)
            logger.warning("Job %s (%s) attempt %d failed: %s", job_id, kind, attempt, last_error)
            if attempt < max_attempts:
                sleep(backoff_base_s * 2 ** (attempt - 1))
            continue
        _update_job(db_factory, job_id, status="done", finished_at=clock.utcnow(), error=None)
        return result

    _update_job(db_factory, job_id, status="failed", error=last_error, finished_at=clock.utcnow())
    if not alert_on_failure:
        return None
    with db_factory() as db:
        if _recent_all_failed(db, kind):
            send_alert(db, "urgent", f"Tác vụ {kind} thất bại 3 lần liên tiếp — cần kiểm tra")
        else:
            send_alert(db, "warn", f"Tác vụ {kind} thất bại sau {max_attempts} lần: {last_error}")
    return None
