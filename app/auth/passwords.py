from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_PASSWORD_LENGTH = 10

_hasher = PasswordHasher()
# Precomputed so unknown-username logins pay the same verify cost as real ones.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-equalisation")


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(hash_: str, plain: str) -> bool:
    """Return True on match; False on mismatch or malformed hash (never raises)."""
    try:
        return _hasher.verify(hash_, plain)
    except (VerificationError, InvalidHashError):
        return False


def dummy_verify() -> None:
    verify_password(_DUMMY_HASH, "wrong-password")


def validate_new_password(plain: str) -> str | None:
    """Return a Vietnamese error message, or None when the password is acceptable."""
    if len(plain) < MIN_PASSWORD_LENGTH:
        return f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự"
    return None
