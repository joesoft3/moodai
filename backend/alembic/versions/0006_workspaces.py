"""add workspaces + workspace_members; conversations.workspace_id; messages.user_id (guarded)

Revision ID: 0006_workspaces
Revises: 0005_pending_actions
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_workspaces"
down_revision = "0005_pending_actions"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    if "workspaces" not in tables:
        op.create_table(
            "workspaces",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])

    if "workspace_members" not in tables:
        op.create_table(
            "workspace_members",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(20), nullable=False, server_default="member"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"])
        op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])

    conv_cols = [c["name"] for c in insp.get_columns("conversations")]
    if "workspace_id" not in conv_cols:
        op.add_column(
            "conversations",
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        )
        op.create_index("ix_conversations_workspace_id", "conversations", ["workspace_id"])

    msg_cols = [c["name"] for c in insp.get_columns("messages")]
    if "user_id" not in msg_cols:
        op.add_column(
            "messages",
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "user_id" in [c["name"] for c in insp.get_columns("messages")]:
        op.drop_column("messages", "user_id")
    if "workspace_id" in [c["name"] for c in insp.get_columns("conversations")]:
        op.drop_column("conversations", "workspace_id")
    for t in ("workspace_members", "workspaces"):
        if t in insp.get_table_names():
            op.drop_table(t)
