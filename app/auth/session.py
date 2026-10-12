import hashlib
import secrets
import uuid
from datetime import timedelta

from fastapi import Response
from sqlalchemy import delete, orm, select

from app import clock
from app.config import get_settings
from app.db.models import User, UserSession


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def cookie_secure() -> bool:
    """Secure flag is on everywhere except local development."""
    return get_settings().APP_ENV != "dev"


def create_session(
    db: orm.Session,
    user: User,
    remember: bool,
    ip: str | None,
    user_agent: str | None,
) -> str:
    """Create a server-side session and return the raw token (only the hash is stored)."""
    settings = get_settings()
    now = clock.utcnow()
    lifetime = (
        timedelta(days=settings.SESSION_REMEMBER_DAYS)
        if remember
        else timedelta(seconds=settings.SESSION_MAX_AGE_SECONDS)
    )
    raw = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(raw),
            remember_me=remember,
            expires_at=now + lifetime,
            last_seen_at=now,
            ip=ip,
            user_agent=user_agent[:500] if user_agent else None,
        )
    )
    db.commit()
    return raw


def resolve_session(db: orm.Session, raw_token: str | None) -> User | None:
    """Return the active user for a live session, or None. Slides non-remember expiry."""
    if not raw_token:
        return None
    row = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(raw_token)))
    if row is None:
        return None
    now = clock.utcnow()
    if row.expires_at <= now:
        db.delete(row)
        db.commit()
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    row.last_seen_at = now
    if not row.remember_me:
        row.expires_at = now + timedelta(seconds=get_settings().SESSION_MAX_AGE_SECONDS)
    db.commit()
    return user


def destroy_session(db: orm.Session, raw_token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(raw_token)))
    db.commit()


def destroy_user_sessions(
    db: orm.Session, user_id: uuid.UUID, except_token: str | None = None
) -> None:
    stmt = delete(UserSession).where(UserSession.user_id == user_id)
    if except_token is not None:
        stmt = stmt.where(UserSession.token_hash != hash_token(except_token))
    db.execute(stmt)
    db.commit()


def set_session_cookie(response: Response, token: str, remember: bool) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        token,
        max_age=settings.SESSION_REMEMBER_DAYS * 86400 if remember else None,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
    )
