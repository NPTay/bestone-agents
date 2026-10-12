import argparse
import getpass
import sys

from sqlalchemy import delete, select

from app.audit import write_audit
from app.auth.passwords import hash_password, validate_new_password
from app.cli import use_utf8_console
from app.db.models import User, UserSession
from app.db.session import open_session


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(description="Đặt lại mật khẩu tài khoản")
    parser.add_argument("--username", required=True)
    args = parser.parse_args(argv)

    with open_session() as db:
        user = db.scalar(select(User).where(User.username == args.username))
        if user is None:
            print("Không tìm thấy tài khoản", file=sys.stderr)
            return 1
        first = getpass.getpass("Mật khẩu mới: ")
        second = getpass.getpass("Mật khẩu mới: ")
        if first != second:
            print("Hai lần nhập không khớp", file=sys.stderr)
            return 1
        error = validate_new_password(first)
        if error:
            print(error, file=sys.stderr)
            return 1
        user.password_hash = hash_password(first)
        user.failed_attempts = 0
        user.last_failed_at = None
        user.locked_until = None
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        write_audit(
            db, None, "password_reset_cli", "user", str(user.id), {"username": user.username}
        )
        db.commit()
    print(f"Đã đặt lại mật khẩu cho: {args.username}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
