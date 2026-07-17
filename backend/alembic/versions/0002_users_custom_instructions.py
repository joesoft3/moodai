"""add users.custom_instructions (guarded — for databases created before migrations existed)

Revision ID: 0002_users_custom_instructions
Revises: 0001_initial
Create Date: 2026-07-17

The baseline (0001) already includes this column, so this is a no-op for fresh
installs. For databases stamped on 0001 that predate the column, it adds it.
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_users_custom_instructions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("users")]
    if "custom_instructions" not in columns:
        op.add_column("users", sa.Column("custom_instructions", sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("users")]
    if "custom_instructions" in columns:
        op.drop_column("users", "custom_instructions")
