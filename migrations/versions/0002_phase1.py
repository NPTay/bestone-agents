"""phase 1: post review fields, research metadata, planner slot uniqueness

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12 20:00:00.000000

PostgreSQL notes:
* ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction block on older servers and the
  new label cannot be used in the same transaction, so it is issued in an autocommit block
  before any other DDL. ``IF NOT EXISTS`` makes re-runs safe.
* Downgrade cannot remove an enum label in PostgreSQL; ``rejected`` is left in ``post_status``
  (harmless: no column uses it after the downgrade, and re-upgrade is a no-op for it).
  Rows with status ``rejected`` are mapped back to ``draft`` first so SQLite/PG data stays valid.
* On SQLite the enum is a plain VARCHAR (no CHECK constraint), so no change is needed there.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
EMPTY_LIST = sa.text("'[]'")
FK_NAME = "fk_posts_research_item_id_research_items"
UQ_NAME = "uq_posts_planned_pillar"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE post_status ADD VALUE IF NOT EXISTS 'rejected'")

    with op.batch_alter_table("research_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("angle_suggestion", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("score_reasons", JSON, nullable=False, server_default=EMPTY_LIST)
        )
        batch_op.add_column(
            sa.Column("risk_flags", JSON, nullable=False, server_default=EMPTY_LIST)
        )
        batch_op.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cta", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("alt_opening", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("sensitive_reasons", JSON, nullable=False, server_default=EMPTY_LIST)
        )
        batch_op.add_column(sa.Column("rejection_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("planned_for", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("research_item_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(FK_NAME, "research_items", ["research_item_id"], ["id"])
        batch_op.create_unique_constraint(UQ_NAME, ["planned_for", "pillar"])


def downgrade() -> None:
    op.execute("UPDATE posts SET status = 'draft' WHERE status = 'rejected'")

    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.drop_constraint(UQ_NAME, type_="unique")
        batch_op.drop_constraint(FK_NAME, type_="foreignkey")
        batch_op.drop_column("research_item_id")
        batch_op.drop_column("planned_for")
        batch_op.drop_column("rejection_reason")
        batch_op.drop_column("sensitive_reasons")
        batch_op.drop_column("alt_opening")
        batch_op.drop_column("cta")

    with op.batch_alter_table("research_items", schema=None) as batch_op:
        batch_op.drop_column("published_at")
        batch_op.drop_column("risk_flags")
        batch_op.drop_column("score_reasons")
        batch_op.drop_column("angle_suggestion")
