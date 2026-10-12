from app.auth.passwords import (
    dummy_verify,
    hash_password,
    validate_new_password,
    verify_password,
)


def test_hash_roundtrip() -> None:
    h = hash_password("Matkhau#2026")
    assert h.startswith("$argon2")
    assert verify_password(h, "Matkhau#2026") and not verify_password(h, "sai")


def test_verify_never_raises_on_garbage_hash() -> None:
    assert verify_password("not-a-hash", "x") is False


def test_dummy_verify_runs() -> None:
    assert dummy_verify() is None


def test_validate_new_password() -> None:
    assert validate_new_password("Matkhau#2026") is None
    err = validate_new_password("ngan")
    assert err is not None and "10 ký tự" in err
