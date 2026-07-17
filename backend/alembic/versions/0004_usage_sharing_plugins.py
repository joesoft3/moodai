"""add usage_events, shared_links, plugin_connections (guarded, idempotent)

Revision ID: 0004_usage_sharing_plugins
Revises: 0003_conversations_summary
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_usage_sharing_plugins"
down_revision = "0003_conversations_summary"
branch_labels = None
depends_on = None


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "usage_events"):
        op.create_table(
            "usage_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(24), nullable=False),
            sa.Column("model", sa.String(80), nullable=True),
            sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("estimated", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_usage_events_user_id", "usage_events", ["user_id"])
        op.create_index("ix_usage_events_kind", "usage_events", ["kind"])
        op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"])

    if not _has_table(insp, "shared_links"):
        op.create_table(
            "shared_links",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("token", sa.String(64), nullable=False),
            sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_shared_links_token", "shared_links", ["token"], unique=True)
        op.create_index("ix_shared_links_conversation_id", "shared_links", ["conversation_id"])
        op.create_index("ix_shared_links_user_id", "shared_links", ["user_id"])

    if not _has_table(insp, "plugin_connections"):
        op.create_table(
            "plugin_connections",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("account", sa.String(255), nullable=True),
            sa.Column("access_token_enc", sa.Text(), nullable=False),
            sa.Column("refresh_token_enc", sa.Text(), nullable=True),
            sa.Column("scopes", sa.String(500), nullable=False, server_default=""),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_plugin_connections_user_id", "plugin_connections", ["user_id"])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for t in ("plugin_connections", "shared_links", "usage_events"):
        if _has_table(insp, t):
            op.drop_table(t)
