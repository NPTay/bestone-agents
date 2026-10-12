import uuid
from typing import Any

from sqlalchemy import orm

from app.db.models import AuditLog


def write_audit(
    db: orm.Session,
    actor_id: uuid.UUID | None,
    action: str,
    entity: str,
    entity_id: str | None,
    detail: dict[str, Any],
) -> None:
    """Add an audit row to the session (caller commits). Never put secrets in detail."""
    db.add(
        AuditLog(actor=actor_id, action=action, entity=entity, entity_id=entity_id, detail=detail)
    )
