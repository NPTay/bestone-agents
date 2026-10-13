"""Daily tick: derive every action from DB state and local time (restart-safe)."""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.content.images import ImagePlan, ImageResult, get_morning_image
from app.content.pictures import PictureChoice, choose_pictures, parse_projects
from app.content.research import Article, find_candidates, load_queries
from app.content.writer import MorningDraft, review, write_afternoon, write_morning
from app.db.models import Post, ResearchItem, Setting
from app.guardrails.judge import GuardrailReport
from app.integrations.notify import send_alert
from app.jobs import run_job
from app.llm.client import LLMClient
from app.llm.prompts import PROJECT_ROOT, load_knowledge
from app.meta.graph import GraphClient
from app.posts.publisher import publish_post, recover_stuck, retry_missing_comments
from app.posts.store import PostDraft, claim_slot, due_for_publish, expire_open, save_draft
from app.schedule_times import (
    AFTERNOON_DRAFT,
    DAY_END,
    MORNING_CUTOFF,
    MORNING_DRAFT,
    Slot,
    local_now,
)
from app.telegram.bot import FakeTelegram, TelegramBot, TelegramError
from app.telegram.review import send_for_review_safe

logger = logging.getLogger(__name__)

QUERIES_FILE = PROJECT_ROOT / "config" / "research_queries.txt"
PICTURE_EXCLUDE_FILE = PROJECT_ROOT / "config" / "picture_exclude.txt"
RECENT_DAYS = 14
AGENT = "content"

NO_ARTICLE_ERROR = "Không tìm được tin phù hợp"
NO_ARTICLE_TEXT = "Sáng nay không tìm được tin phù hợp nên không có bài sáng."
NO_PICTURES_NOTE = "⚠️ Thư mục Picture không có ảnh dùng được."
NO_LLM_ERROR = "Chưa cấu hình AI"
JOB_FAILED_ERROR = "Soạn bài thất bại"
INTERRUPTED_ERROR = "Bị gián đoạn khi đang soạn"
SLOT_CUTOFF: dict[str, dtime] = {"morning": MORNING_CUTOFF, "afternoon": DAY_END}
RETRY_PREFIX = "DRAFT_RETRY:"
MAX_DRAFT_TRIES = 3
RETRY_GAP = timedelta(minutes=10)
NOTIFIED = "notified"
SLOT_VI: dict[str, str] = {"morning": "sáng", "afternoon": "chiều"}

ImageFn = Callable[[ImagePlan, Path, Settings], ImageResult]
ResearchFn = Callable[..., list[Article]]


@dataclass
class Deps:
    db_factory: Callable[[], Session]
    llm: LLMClient | None
    bot: TelegramBot | FakeTelegram
    graph: GraphClient | None
    settings: Settings
    image_fn: ImageFn = get_morning_image
    research_fn: ResearchFn = find_candidates
    max_attempts: int = 3
    sleep: Callable[[float], None] = field(default=time.sleep)


@dataclass
class _Context:
    kb: str
    unverified: list[str]
    recent_titles: list[str]


@dataclass
class _MorningResult:
    draft: MorningDraft | None = None
    article: Article | None = None
    report: GuardrailReport | None = None
    blocking: bool = False
    image: ImageResult | None = None


@dataclass
class _AfternoonResult:
    draft: PostDraft
    report: GuardrailReport
    blocking: bool
    choice: PictureChoice | None


# --- helpers -----------------------------------------------------------------


def _context(db: Session, day: date) -> _Context:
    kb = load_knowledge()["bestone_knowledge_base.md"]
    unverified = [name for name, info in parse_projects(kb).items() if not info.verified]
    since = day - timedelta(days=RECENT_DAYS)
    titles = db.scalars(
        select(Post.title).where(Post.day >= since, Post.day <= day, Post.title != "")
    ).all()
    return _Context(kb=kb, unverified=unverified, recent_titles=list(titles))


def _load_context(deps: Deps, day: date) -> _Context:
    with deps.db_factory() as db:
        return _context(db, day)


def _claim(deps: Deps, day: date, slot: Slot) -> uuid.UUID | None:
    with deps.db_factory() as db:
        post = claim_slot(db, day, slot)
        return None if post is None else post.id


# Retry state: Setting "DRAFT_RETRY:{day}:{slot}" = "{count}|{iso_utc}[|notified]".


@dataclass
class _RetryState:
    count: int
    last: datetime
    notified: bool


def _retry_key(day: date, slot: str) -> str:
    return f"{RETRY_PREFIX}{day.isoformat()}:{slot}"


def _parse_retry(value: str) -> _RetryState:
    parts = value.split("|")
    return _RetryState(int(parts[0]), datetime.fromisoformat(parts[1]), NOTIFIED in parts[2:])


def _format_retry(state: _RetryState) -> str:
    value = f"{state.count}|{state.last.astimezone(UTC).isoformat()}"
    return value + f"|{NOTIFIED}" if state.notified else value


def _get_retry(db: Session, day: date, slot: str) -> tuple[Setting | None, _RetryState | None]:
    row = db.scalar(select(Setting).where(Setting.key == _retry_key(day, slot)))
    return row, (None if row is None else _parse_retry(row.value))


def _retry_allowed(deps: Deps, day: date, slot: Slot, now: datetime) -> bool:
    with deps.db_factory() as db:
        _row, state = _get_retry(db, day, slot)
    if state is None:
        return True
    return state.count < MAX_DRAFT_TRIES and now >= state.last + RETRY_GAP


def _retryable_failure(
    deps: Deps, post_id: uuid.UUID, day: date, slot: Slot, now: datetime, error: str, alert: str
) -> None:
    """Free the slot for a later retry; after the last try keep a failed row and alert."""
    with deps.db_factory() as db:
        row, state = _get_retry(db, day, slot)
        count = (state.count if state else 0) + 1
        new_value = _format_retry(_RetryState(count, now, False))
        if row is None:
            db.add(Setting(key=_retry_key(day, slot), value=new_value))
        else:
            row.value = new_value
        final = count >= MAX_DRAFT_TRIES
        post = db.get(Post, post_id)
        if post is not None and post.status == "drafting":
            if final:
                post.status = "failed"
                post.error = error
            else:
                db.delete(post)
        db.commit()
        if final:
            send_alert(db, "warn", alert)


def _tell(deps: Deps, db: Session, text: str) -> None:
    """Send a plain Telegram message; fall back to an alert row if it fails."""
    try:
        deps.bot.send_message(text)
    except (TelegramError, OSError) as exc:
        logger.warning("Telegram message failed: %s", type(exc).__name__)
        send_alert(db, "warn", text)


def _fail_post(deps: Deps, post_id: uuid.UUID, error: str, alert: str | None) -> None:
    with deps.db_factory() as db:
        post = db.get(Post, post_id)
        if post is not None and post.status == "drafting":
            post.status = "failed"
            post.error = error
            db.commit()
        if alert:
            send_alert(db, "warn", alert)


def _send(deps: Deps, db: Session, post: Post) -> None:
    message_id = send_for_review_safe(deps.bot, post, db)
    if message_id is not None:
        post.telegram_message_id = message_id
        db.commit()


def _no_llm_alert(slot: Slot) -> str:
    return f"Không soạn được bài {SLOT_VI[slot]}: chưa cấu hình AI."


def _job_failed_alert(slot: Slot) -> str:
    return f"Không soạn được bài {SLOT_VI[slot]} hôm nay (lỗi khi tìm tin/viết bài)."


def _guarded(deps: Deps, post_id: uuid.UUID, fn: Callable[[], None]) -> None:
    """Run the drafting body; never leave the claimed row stuck in `drafting`."""
    try:
        fn()
    except Exception:
        _fail_post(deps, post_id, JOB_FAILED_ERROR, None)
        raise


# --- drafting ----------------------------------------------------------------


def draft_morning(deps: Deps, day: date, now: datetime) -> None:
    if not _retry_allowed(deps, day, "morning", now):
        return
    post_id = _claim(deps, day, "morning")
    if post_id is None:
        return
    _guarded(deps, post_id, lambda: _draft_morning(deps, day, now, post_id))


def _draft_morning(deps: Deps, day: date, now: datetime, post_id: uuid.UUID) -> None:
    llm = deps.llm
    if llm is None:
        _retryable_failure(
            deps, post_id, day, "morning", now, NO_LLM_ERROR, _no_llm_alert("morning")
        )
        return
    ctx = _load_context(deps, day)
    queries = load_queries(QUERIES_FILE)

    def work(db: Session, job_id: uuid.UUID) -> _MorningResult:
        articles = deps.research_fn(llm, db, queries, job_id, day=day)
        if not articles:
            return _MorningResult()
        draft = write_morning(llm, articles, ctx.kb, ctx.recent_titles, job_id)
        if draft is None:
            return _MorningResult()
        article = next(a for a in articles if a.url == draft.article_url)
        report, blocking = review(llm, draft, ctx.kb, [article.text], ctx.unverified, job_id)
        media_dir = Path(deps.settings.DATA_DIR) / "media"
        image = deps.image_fn(draft.image_plan, media_dir, deps.settings)
        return _MorningResult(draft, article, report, blocking, image)

    result = run_job(
        deps.db_factory,
        agent=AGENT,
        kind="draft_morning",
        payload={"day": day.isoformat(), "post_id": str(post_id)},
        fn=work,
        max_attempts=deps.max_attempts,
        sleep=deps.sleep,
    )
    if result is None:
        _retryable_failure(
            deps, post_id, day, "morning", now, JOB_FAILED_ERROR, _job_failed_alert("morning")
        )
        return
    if result.draft is None or result.article is None or result.report is None:
        _fail_post(deps, post_id, NO_ARTICLE_ERROR, None)
        with deps.db_factory() as db:
            _tell(deps, db, NO_ARTICLE_TEXT)
        return

    with deps.db_factory() as db:
        post = db.get(Post, post_id)
        assert post is not None
        image = result.image or ImageResult()
        post.image_paths = list(image.paths)
        post.image_note = image.note or None
        post.source_text = result.article.text
        post.research_url = result.article.url
        item = db.scalar(select(ResearchItem).where(ResearchItem.url == result.article.url))
        if item is not None:
            item.used_post_id = post.id
        # review() may have fixed the draft in place (R5): save that same object.
        save_draft(db, post, result.draft, result.report, result.blocking)
        _send(deps, db, post)


def draft_afternoon(deps: Deps, day: date, now: datetime) -> None:
    if not _retry_allowed(deps, day, "afternoon", now):
        return
    post_id = _claim(deps, day, "afternoon")
    if post_id is None:
        return
    _guarded(deps, post_id, lambda: _draft_afternoon(deps, day, now, post_id))


def _draft_afternoon(deps: Deps, day: date, now: datetime, post_id: uuid.UUID) -> None:
    llm = deps.llm
    if llm is None:
        _retryable_failure(
            deps, post_id, day, "afternoon", now, NO_LLM_ERROR, _no_llm_alert("afternoon")
        )
        return
    ctx = _load_context(deps, day)
    picture_dir = Path(deps.settings.PICTURE_DIR)

    def work(db: Session, job_id: uuid.UUID) -> _AfternoonResult:
        choice = choose_pictures(db, picture_dir, PICTURE_EXCLUDE_FILE, ctx.kb)
        draft = write_afternoon(llm, choice, ctx.kb, ctx.recent_titles, job_id)
        report, blocking = review(llm, draft, ctx.kb, [], ctx.unverified, job_id)
        return _AfternoonResult(draft, report, blocking, choice)

    result = run_job(
        deps.db_factory,
        agent=AGENT,
        kind="draft_afternoon",
        payload={"day": day.isoformat(), "post_id": str(post_id)},
        fn=work,
        max_attempts=deps.max_attempts,
        sleep=deps.sleep,
    )
    if result is None:
        _retryable_failure(
            deps, post_id, day, "afternoon", now, JOB_FAILED_ERROR, _job_failed_alert("afternoon")
        )
        return

    with deps.db_factory() as db:
        post = db.get(Post, post_id)
        assert post is not None
        if result.choice is not None:
            root = picture_dir.resolve()
            post.image_paths = [str(root / rel) for rel in result.choice.paths]
            post.picture_folder = result.choice.folder
            post.image_note = None
        else:
            post.image_paths = []
            post.image_note = NO_PICTURES_NOTE
        save_draft(db, post, result.draft, result.report, result.blocking)
        _send(deps, db, post)


# --- tick ----------------------------------------------------------------------


def _expiry_text(post: Post, previous: str) -> str:
    label = f"Bài {SLOT_VI[post.slot]} {post.day:%d/%m}"
    if previous == "approved":
        return f"⏰ {label} đã được duyệt nhưng máy tắt nên không đăng được trong ngày, đã bỏ."
    if post.telegram_message_id is None:
        return f"⏰ {label} chưa gửi được lên Telegram nên đã bỏ."
    return f"⏰ {label} chưa được duyệt trước 20:00 nên đã bỏ."


def _expire(deps: Deps, now: datetime) -> None:
    with deps.db_factory() as db:
        for post, previous in expire_open(db, now):
            if post.telegram_message_id is not None:
                try:
                    deps.bot.edit_buttons_removed(post.telegram_message_id)
                except (TelegramError, OSError) as exc:
                    logger.warning("Removing buttons failed: %s", type(exc).__name__)
            _tell(deps, db, _expiry_text(post, previous))
        _notify_lost_slots(db, now)


def _notify_lost_slots(db: Session, now: datetime) -> None:
    """Once a day is over, alert once per slot whose drafting kept failing (no row left)."""
    local = local_now(now)
    today, day_over = local.date(), local.time() >= DAY_END
    rows = db.scalars(select(Setting).where(Setting.key.startswith(RETRY_PREFIX))).all()
    for row in rows:
        day_text, slot = row.key.removeprefix(RETRY_PREFIX).split(":")
        day = date.fromisoformat(day_text)
        state = _parse_retry(row.value)
        if state.notified or not (day < today or (day == today and day_over)):
            continue
        has_post = db.scalar(select(Post.id).where(Post.day == day, Post.slot == slot))
        if has_post is None:
            when = "Hôm nay" if day == today else f"Ngày {day:%d/%m}"
            send_alert(
                db, "warn", f"{when} không soạn được bài {SLOT_VI[slot]} (lỗi kết nối/AI)."
            )
        state.notified = True
        row.value = _format_retry(state)
        db.commit()


def _resend_unsent(deps: Deps, now: datetime) -> None:
    """Retry sending today's pending posts that never reached Telegram."""
    today = local_now(now).date()
    with deps.db_factory() as db:
        unsent = db.scalars(
            select(Post).where(
                Post.day == today,
                Post.status == "pending",
                Post.telegram_message_id.is_(None),
            )
        ).all()
        for post in unsent:
            # alert=False: the first send already alerted; don't repeat every minute.
            message_id = send_for_review_safe(deps.bot, post, db, alert=False)
            if message_id is not None:
                post.telegram_message_id = message_id
                db.commit()


def _publish_due(deps: Deps, now: datetime) -> None:
    with deps.db_factory() as db:
        for post in due_for_publish(db, now):
            try:
                publish_post(db, deps.graph, deps.bot, post, now, deps.settings.DRY_RUN)
            except Exception as exc:
                db.rollback()
                logger.error("Publishing post %s failed: %s", post.id, type(exc).__name__)
                send_alert(
                    db, "warn", f"Lỗi khi đăng bài {SLOT_VI[post.slot]}: {type(exc).__name__}"
                )


def _retry_comments(deps: Deps, now: datetime) -> None:
    with deps.db_factory() as db:
        retry_missing_comments(db, deps.graph, now)


def _step(deps: Deps, name: str, fn: Callable[[], None]) -> None:
    """Run one tick step; a failure is logged and alerted, never propagated."""
    try:
        fn()
    except Exception as exc:
        # Type only: exception messages may carry URLs with tokens.
        logger.error("Tick step %s failed: %s", name, type(exc).__name__)
        try:
            with deps.db_factory() as db:
                send_alert(db, "warn", f"Lỗi ở bước {name}: {type(exc).__name__}")
        except Exception as alert_exc:
            logger.error("Alert for step %s failed: %s", name, type(alert_exc).__name__)


def tick(deps: Deps, now: datetime) -> None:
    local = local_now(now)
    today, at = local.date(), local.time()
    # Expire first: an old approved post must never be published after its day.
    _step(deps, "expire", lambda: _expire(deps, now))
    _step(deps, "resend", lambda: _resend_unsent(deps, now))
    if MORNING_DRAFT <= at < MORNING_CUTOFF:
        _step(deps, "draft_morning", lambda: draft_morning(deps, today, now))
    if AFTERNOON_DRAFT <= at < DAY_END:
        _step(deps, "draft_afternoon", lambda: draft_afternoon(deps, today, now))
    _step(deps, "publish", lambda: _publish_due(deps, now))
    _step(deps, "comments", lambda: _retry_comments(deps, now))


def _recover_drafting(deps: Deps, now: datetime) -> None:
    """Only one instance runs, so a `drafting` row at startup was orphaned by a shutdown."""
    local = local_now(now)
    with deps.db_factory() as db:
        orphans = db.scalars(
            select(Post).where(Post.day == local.date(), Post.status == "drafting")
        ).all()
        for post in orphans:
            if local.time() < SLOT_CUTOFF[post.slot]:
                db.delete(post)  # window still open: the next tick redrafts it
                db.commit()
                continue
            post.status = "failed"
            post.error = INTERRUPTED_ERROR
            db.commit()
            send_alert(
                db,
                "warn",
                f"Bài {SLOT_VI[post.slot]} {post.day:%d/%m} bị gián đoạn khi đang soạn "
                "(máy tắt) nên không có bài.",
            )


def startup(deps: Deps, now: datetime) -> None:
    def recover() -> None:
        with deps.db_factory() as db:
            recover_stuck(db, deps.bot)

    _step(deps, "recover", recover)
    _step(deps, "recover_drafting", lambda: _recover_drafting(deps, now))
    tick(deps, now)
