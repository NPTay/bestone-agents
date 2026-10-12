from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import orm, text

from app.db.session import get_db

router = APIRouter()


def check_db(db: orm.Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


@router.get("/health")
def health(db: orm.Session = Depends(get_db)) -> JSONResponse:  # noqa: B008
    if check_db(db):
        return JSONResponse({"status": "ok", "db": "ok"})
    return JSONResponse({"status": "error", "db": "error"}, status_code=503)
