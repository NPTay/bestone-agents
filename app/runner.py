"""Desktop runner: one process with the tick loop, the Telegram poller and the dashboard."""

import logging
import os
import sys
import threading
import time
import traceback
import webbrowser
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import IO, Any

import httpx
import uvicorn
from sqlalchemy import Engine

from app import clock
from app.config import Settings, get_settings
from app.db.init import init_db
from app.db.session import _sessionmaker
from app.llm.client import get_llm
from app.meta.graph import GraphClient
from app.scheduler import Deps, startup, tick
from app.telegram.bot import TelegramBot, TelegramError
from app.telegram.handler import poll_once
from app.web.app import create_app

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
TICK_SECONDS = 60
POLL_ERROR_PAUSE = 3.0
BROWSER_WAIT_SECONDS = 15
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
STARTED_TEXT = "🟢 Chương trình Bestone đã chạy."
DRY_RUN_SUFFIX = " (chạy thử – chưa đăng thật)"


def acquire_single_instance(lock_path: Path) -> object | None:
    """Take an exclusive non-blocking lock; keep the returned handle open while running."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle: IO[bytes] = open(lock_path, "a+b")  # held for the process lifetime
    try:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


class NullTelegram(TelegramBot):
    """Stand-in when Telegram is not configured: logs and raises instead of sending.

    Raising TelegramError (rather than faking a message id) keeps posts marked as
    unsent, and every caller already handles TelegramError.
    """

    def __init__(self) -> None:
        super().__init__("", "", client=httpx.Client())

    def _call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: list[tuple[str, Any]] | None = None,
    ) -> Any:
        logger.info("Telegram not configured; skipped %s", method)
        raise TelegramError(f"{method} skipped: Telegram not configured")


def _configure_logging(settings: Settings) -> list[logging.Handler]:
    log_dir = Path(settings.DATA_DIR) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_dir / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
    ]
    if sys.stderr is not None:  # pythonw has no console
        handlers.append(logging.StreamHandler())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    # Telegram URLs embed the bot token; httpx logs full URLs at INFO (R6).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)  # used by the anthropic SDK
    return handlers


def _remove_handlers(handlers: list[logging.Handler]) -> None:
    root = logging.getLogger()
    for handler in handlers:
        root.removeHandler(handler)
        handler.close()


def _build_bot(settings: Settings) -> TelegramBot:
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_ADMIN_CHAT_ID:
        return TelegramBot(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_ADMIN_CHAT_ID)
    logger.warning("Chưa cấu hình Telegram (TELEGRAM_BOT_TOKEN/TELEGRAM_ADMIN_CHAT_ID)")
    return NullTelegram()


def _build_graph(settings: Settings) -> GraphClient | None:
    if settings.META_PAGE_ACCESS_TOKEN and settings.META_PAGE_ID:
        return GraphClient(settings)
    logger.warning("Chưa cấu hình Facebook (META_PAGE_ID/META_PAGE_ACCESS_TOKEN)")
    return None


def _loop(name: str, stop: threading.Event, body: Callable[[], None], pause: float) -> None:
    """Run `body` until stopped; exceptions are logged by type only, never propagated."""
    while not stop.is_set():
        try:
            body()
        except Exception as exc:
            logger.error("%s loop error: %s", name, type(exc).__name__)
        if pause:
            stop.wait(pause)


def _tick_worker(deps: Deps, stop: threading.Event) -> None:
    try:
        startup(deps, clock.utcnow())
    except Exception as exc:
        logger.error("Startup failed: %s", type(exc).__name__)
    stop.wait(TICK_SECONDS)
    _loop("tick", stop, lambda: tick(deps, clock.utcnow()), TICK_SECONDS)


def _poll_worker(deps: Deps, bot: TelegramBot, stop: threading.Event) -> None:
    def body() -> None:
        started = time.monotonic()
        poll_once(deps.db_factory, bot, deps.llm, deps.settings, clock.utcnow)
        # getUpdates long-polls 30 s; a quick return usually means an error, so pause.
        if time.monotonic() - started < 1.0:
            stop.wait(POLL_ERROR_PAUSE)

    _loop("telegram", stop, body, 0)


def _open_browser_when_ready(port: int) -> None:
    health = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + BROWSER_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            if httpx.get(health, timeout=2).status_code == 200:
                webbrowser.open(f"http://127.0.0.1:{port}/")
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    logger.warning("Dashboard did not answer /health within %s s", BROWSER_WAIT_SECONDS)


def _announce(bot: TelegramBot, settings: Settings) -> None:
    text = STARTED_TEXT + (DRY_RUN_SUFFIX if settings.DRY_RUN else "")
    try:
        bot.send_message(text)
    except (TelegramError, OSError) as exc:
        logger.warning("Startup message not sent: %s", type(exc).__name__)


def run(settings: Settings, open_browser: bool = True) -> int:
    """Run until Ctrl+C. `settings` must be `get_settings()` (the publisher reads that)."""
    previous_level = logging.getLogger().level
    handlers = _configure_logging(settings)
    try:
        lock = acquire_single_instance(Path(settings.DATA_DIR) / "bestone.lock")
        if lock is None:
            logger.info("Chương trình đã đang chạy; thoát bản thứ hai.")
            return 0
        try:
            return _serve(settings, open_browser)
        except Exception as exc:
            # Log before the file handler goes: under pythonw stderr is None.
            # Type and frames only; str(exc) may carry a secret (e.g. a DB URL).
            frames = "".join(traceback.format_tb(exc.__traceback__))
            logger.error("Run failed: %s\n%s", type(exc).__name__, frames)
            return 1
        finally:
            lock.close()  # type: ignore[attr-defined]
    finally:
        _remove_handlers(handlers)
        logging.getLogger().setLevel(previous_level)


def _serve(settings: Settings, open_browser: bool) -> int:
    logger.info("Starting Bestone (DRY_RUN=%s)", settings.DRY_RUN)
    factory = _sessionmaker()
    engine: Engine = factory.kw["bind"]
    init_db(engine)

    llm = get_llm()
    if llm is None:
        logger.warning("Chưa cấu hình AI (ANTHROPIC_API_KEY)")
    bot = _build_bot(settings)
    deps = Deps(
        db_factory=factory, llm=llm, bot=bot, graph=_build_graph(settings), settings=settings
    )
    _announce(bot, settings)

    stop = threading.Event()
    threading.Thread(
        target=_tick_worker, args=(deps, stop), name="tick", daemon=True
    ).start()
    if not isinstance(bot, NullTelegram):
        poll_bot = TelegramBot(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_ADMIN_CHAT_ID)
        threading.Thread(
            target=_poll_worker, args=(deps, poll_bot, stop), name="telegram", daemon=True
        ).start()
    if open_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(settings.DASHBOARD_PORT,),
            name="browser",
            daemon=True,
        ).start()

    app = create_app(factory, settings)
    try:
        # log_config=None: uvicorn's default config writes to a console pythonw lacks.
        uvicorn.run(app, host="127.0.0.1", port=settings.DASHBOARD_PORT, log_config=None)
    except SystemExit as exc:  # e.g. port already in use
        logger.error("Dashboard server stopped: exit %s", exc.code)
        return 1
    finally:
        stop.set()
    logger.info("Stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    # Relative DATABASE_URL, DATA_DIR and PICTURE_DIR resolve against the repo root (R15).
    os.chdir(REPO_ROOT)
    get_settings.cache_clear()
    _sessionmaker.cache_clear()
    get_llm.cache_clear()
    return run(get_settings(), open_browser="--no-browser" not in args)
