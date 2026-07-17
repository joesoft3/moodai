"""domain white-label arena: per-domain panel/judge/quota/branding

Revision ID: 0010_domain_arena
Revises: 0009_admin_ops
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_domain_arena"
down_revision = "0009_admin_ops"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "domains" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("domains")}
        if "arena_enabled" not in cols:
            op.add_column(
                "domains", sa.Column("arena_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if "arena_daily_cap" not in cols:
            op.add_column(
                "domains", sa.Column("arena_daily_cap", sa.Integer(), nullable=False, server_default="0")
            )
        if "arena_brand" not in cols:
            op.add_column("domains", sa.Column("arena_brand", sa.String(80), nullable=True))
        if "arena_judge" not in cols:
            op.add_column("domains", sa.Column("arena_judge", sa.String(60), nullable=True))
        if "arena_panel" not in cols:
            op.add_column("domains", sa.Column("arena_panel", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "domains" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("domains")}
        for name in ("arena_panel", "arena_judge", "arena_brand", "arena_daily_cap", "arena_enabled"):
            if name in cols:
                op.drop_column("domains", name)
