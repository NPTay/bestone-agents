from fastapi import APIRouter, Depends

from app.auth.dependencies import require_role
from app.db.models import Role

router = APIRouter(prefix="/admin_api")


@router.get("/ping", dependencies=[Depends(require_role(Role.giam_doc))])
def ping() -> dict[str, bool]:
    return {"ok": True}
