import os
import sys

from sqlalchemy import select

from app.audit import write_audit
from app.auth.passwords import hash_password, validate_new_password
from app.cli import use_utf8_console
from app.db.models import Role, User
from app.db.session import open_session


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    username = os.environ.get("INITIAL_ADMIN_USERNAME", "").strip()
    password = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
    if not username or not password:
        print("Thiếu INITIAL_ADMIN_USERNAME hoặc INITIAL_ADMIN_PASSWORD", file=sys.stderr)
        return 1
    error = validate_new_password(password)
    if error:
        print(error, file=sys.stderr)
        return 1
    with open_session() as db:
        if db.scalar(select(User.id).where(User.role == Role.giam_doc).limit(1)) is not None:
            print("Đã có tài khoản Giám đốc, không tạo thêm.", file=sys.stderr)
            return 1
        user = User(
            username=username,
            full_name="Giám đốc",
            password_hash=hash_password(password),
            role=Role.giam_doc,
            is_active=True,
        )
        db.add(user)
        db.flush()
        write_audit(db, user.id, "admin_created_cli", "user", str(user.id), {"username": username})
        db.commit()
    print(f"Đã tạo tài khoản Giám đốc: {username}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
