"""add pending_actions table (human-in-the-loop write-tool approvals)

Revision ID: 0005_pending_actions
Revises: 0004_usage_sharing_plugins
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_pending_actions"
down_revision = "0004_usage_sharing_plugins"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "pending_actions" in insp.get_table_names():
        return
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("tool", sa.String(60), nullable=False),
        sa.Column("args", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_pending_actions_user_id", "pending_actions", ["user_id"])
    op.create_index("ix_pending_actions_conversation_id", "pending_actions", ["conversation_id"])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "pending_actions" in insp.get_table_names():
        op.drop_table("pending_actions")
