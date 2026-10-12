"""initial

Revision ID: 0001
Revises:
Create Date: 2026-10-12 16:59:51.015022
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_NAMES = (
    "alert_level",
    "conversation_channel",
    "conversation_status",
    "job_status",
    "lead_score",
    "lead_status",
    "message_direction",
    "message_sender",
    "post_status",
    "research_topic",
    "user_role",
)


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("level", sa.Enum("info", "warn", "urgent", name="alert_level"), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "contacts",
        sa.Column("fb_psid", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=100), nullable=True),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fb_psid"),
    )
    op.create_table(
        "jobs",
        sa.Column("agent", sa.String(length=50), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column(
            "payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True
        ),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "done", "failed", name="job_status"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "users",
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.Enum("giam_doc", "ke_toan", name="user_role"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("telegram_chat_id", sa.String(length=64), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("totp_secret", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "audit_log",
        sa.Column("actor", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity", sa.String(length=100), nullable=True),
        sa.Column("entity_id", sa.String(length=100), nullable=True),
        sa.Column(
            "detail", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "conversations",
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column(
            "channel", sa.Enum("messenger", "comment", name="conversation_channel"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum("open", "waiting_human", "closed", name="conversation_status"),
            nullable=False,
        ),
        sa.Column("last_customer_msg_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_conversations_contact_id"), ["contact_id"], unique=False
        )
        batch_op.create_index(
            "ix_conversations_window_expires_at", ["window_expires_at"], unique=False
        )

    op.create_table(
        "llm_usage",
        sa.Column("agent", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=False),
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=12, scale=6).with_variant(sa.Float(), "sqlite"),
            nullable=False,
        ),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "posts",
        sa.Column("pillar", sa.String(length=100), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "hashtags", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False
        ),
        sa.Column("image_brief", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(length=2000), nullable=True),
        sa.Column(
            "sources", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False
        ),
        sa.Column(
            "kb_refs", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "idea",
                "draft",
                "guardrail_failed",
                "pending_approval",
                "approved",
                "scheduled",
                "published",
                "failed",
                name="post_status",
            ),
            nullable=False,
        ),
        sa.Column("sensitive", sa.Boolean(), nullable=False),
        sa.Column(
            "guardrail_report",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fb_post_id", sa.String(length=100), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.create_index(
            "ix_posts_status_scheduled_at", ["status", "scheduled_at"], unique=False
        )

    op.create_table(
        "sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("remember_me", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sessions_user_id"), ["user_id"], unique=False)

    op.create_table(
        "leads",
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("project_type", sa.String(length=200), nullable=True),
        sa.Column("scale", sa.String(length=200), nullable=True),
        sa.Column("stage", sa.String(length=200), nullable=True),
        sa.Column("timeline", sa.String(length=200), nullable=True),
        sa.Column(
            "score", sa.Enum("HOT", "WARM", "COLD", "SPAM", name="lead_score"), nullable=False
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "score_reasons",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.Enum("new", "contacted", "won", "lost", name="lead_status"), nullable=False
        ),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_leads_contact_id"), ["contact_id"], unique=False)
        batch_op.create_index("ix_leads_score_status", ["score", "status"], unique=False)

    op.create_table(
        "messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.Enum("in", "out", name="message_direction"), nullable=False),
        sa.Column(
            "sender", sa.Enum("customer", "ai", "human", name="message_sender"), nullable=False
        ),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("fb_mid", sa.String(length=200), nullable=True),
        sa.Column(
            "guardrail_report",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("draft", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fb_mid"),
    )
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_messages_conversation_id"), ["conversation_id"], unique=False
        )

    op.create_table(
        "post_metrics",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("reach", sa.Integer(), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("reactions", sa.Integer(), nullable=False),
        sa.Column("comments", sa.Integer(), nullable=False),
        sa.Column("shares", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("post_metrics", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_post_metrics_post_id"), ["post_id"], unique=False)

    op.create_table(
        "research_items",
        sa.Column("source_url", sa.String(length=2000), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "topic",
            sa.Enum(
                "ha_tang",
                "quy_dinh",
                "su_co_tham",
                "du_an_moi",
                "cong_nghe",
                "esg",
                "khac",
                name="research_topic",
            ),
            nullable=False,
        ),
        sa.Column("relevance_score", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_in_post_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["used_in_post_id"],
            ["posts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_url"),
    )

    # Seed runtime settings (human-in-the-loop by default, kill switch off).
    settings = sa.table(
        "settings",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("value", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        settings,
        [
            {
                "id": uuid.uuid4(),
                "key": "AUTONOMY_LEVEL",
                "value": "draft_only",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": uuid.uuid4(),
                "key": "KILL_SWITCH",
                "value": "false",
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("research_items")
    with op.batch_alter_table("post_metrics", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_post_metrics_post_id"))

    op.drop_table("post_metrics")
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_messages_conversation_id"))

    op.drop_table("messages")
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.drop_index("ix_leads_score_status")
        batch_op.drop_index(batch_op.f("ix_leads_contact_id"))

    op.drop_table("leads")
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sessions_user_id"))

    op.drop_table("sessions")
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.drop_index("ix_posts_status_scheduled_at")

    op.drop_table("posts")
    op.drop_table("llm_usage")
    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.drop_index("ix_conversations_window_expires_at")
        batch_op.drop_index(batch_op.f("ix_conversations_contact_id"))

    op.drop_table("conversations")
    op.drop_table("audit_log")
    op.drop_table("users")
    op.drop_table("settings")
    op.drop_table("jobs")
    op.drop_table("contacts")
    op.drop_table("alerts")

    if op.get_bind().dialect.name == "postgresql":
        for name in ENUM_NAMES:
            sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
