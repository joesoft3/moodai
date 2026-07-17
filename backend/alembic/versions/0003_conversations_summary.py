"""add conversations.summary (guarded — for databases created before this migration)

Revision ID: 0003_conversations_summary
Revises: 0002_users_custom_instructions
Create Date: 2026-07-17

Stores the rolling per-conversation summary used for cross-chat recall.
No-op if the column already exists (e.g. dev DB built with AUTO_CREATE_TABLES
after this change shipped).
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_conversations_summary"
down_revision = "0002_users_custom_instructions"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("conversations")]
    if "summary" not in columns:
        op.add_column("conversations", sa.Column("summary", sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("conversations")]
    if "summary" in columns:
        op.drop_column("conversations", "summary")
