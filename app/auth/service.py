from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import orm, select

from app import clock
from app.audit import write_audit
from app.auth.passwords import dummy_verify, verify_password
from app.config import get_settings
from app.db.models import User
from app.integrations.notify import send_alert

MAX_FAILED_ATTEMPTS = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCK_DURATION = timedelta(minutes=15)


@dataclass
class AuthResult:
    user: User | None = None
    error: Literal["invalid", "locked"] | None = None
    locked_until: datetime | None = None


def format_local_time(moment: datetime) -> str:
    """Format a UTC datetime as HH:MM in the configured timezone."""
    tz = ZoneInfo(get_settings().TZ or "Asia/Ho_Chi_Minh")
    return moment.astimezone(tz).strftime("%H:%M")


def authenticate(db: orm.Session, username: str, password: str) -> AuthResult:
    """Check credentials, enforcing lockout. Commits any counter changes."""
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        dummy_verify()  # equalise timing with a real argon2 verify
        return AuthResult(error="invalid")

    now = clock.utcnow()
    if user.locked_until is not None and user.locked_until > now:
        return AuthResult(error="locked", locked_until=user.locked_until)

    password_ok = verify_password(user.password_hash, password)
    if not user.is_active:
        return AuthResult(error="invalid")

    if not password_ok:
        _register_failure(db, user, now)
        return AuthResult(error="invalid")

    user.failed_attempts = 0
    user.last_failed_at = None
    user.locked_until = None
    user.last_login_at = now
    write_audit(db, user.id, "login_success", "user", str(user.id), {})
    db.commit()
    return AuthResult(user=user)


def _register_failure(db: orm.Session, user: User, now: datetime) -> None:
    if user.last_failed_at is None or now - user.last_failed_at > FAILURE_WINDOW:
        user.failed_attempts = 0
    user.failed_attempts += 1
    user.last_failed_at = now
    locked = user.failed_attempts >= MAX_FAILED_ATTEMPTS
    if locked:
        user.locked_until = now + LOCK_DURATION
        write_audit(
            db,
            user.id,
            "account_locked",
            "user",
            str(user.id),
            {"failed_attempts": user.failed_attempts},
        )
    db.commit()
    if locked and user.locked_until is not None:
        send_alert(
            db,
            "warn",
            f"Cảnh báo: tài khoản '{user.username}' bị khóa tạm đến "
            f"{format_local_time(user.locked_until)} sau {MAX_FAILED_ATTEMPTS} lần đăng nhập sai "
            "liên tiếp (nghi ngờ dò mật khẩu).",
        )
