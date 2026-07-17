"""admin ops: users.is_admin + platform_settings table

Revision ID: 0009_admin_ops
Revises: 0008_domain_ops
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_admin_ops"
down_revision = "0008_domain_ops"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "users" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("users")}
        if "is_admin" not in cols:
            op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()))

    if "platform_settings" not in insp.get_table_names():
        op.create_table(
            "platform_settings",
            sa.Column("key", sa.String(60), primary_key=True),
            sa.Column("value", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "platform_settings" in insp.get_table_names():
        op.drop_table("platform_settings")
    if "users" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("users")}
        if "is_admin" in cols:
            op.drop_column("users", "is_admin")
