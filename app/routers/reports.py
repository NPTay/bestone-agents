from fastapi import APIRouter, Depends, Request, Response

from app.auth.dependencies import require_role
from app.db.models import Role, User
from app.web import render_page

router = APIRouter()


@router.get("/reports")
def reports(
    request: Request,
    user: User = Depends(require_role(Role.giam_doc, Role.ke_toan)),  # noqa: B008
) -> Response:
    return render_page(request, "reports/index.html", user)
