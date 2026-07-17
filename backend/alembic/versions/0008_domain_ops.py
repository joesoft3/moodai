"""domain ops: expiry/theme columns on domains + workspace_invites table

Revision ID: 0008_domain_ops
Revises: 0007_domains
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_domain_ops"
down_revision = "0007_domains"
branch_labels = None
depends_on = None


def _columns(insp, table: str) -> set[str]:
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # --- domains: expiry sync + white-label theme columns (idempotent)
    if "domains" in insp.get_table_names():
        cols = _columns(insp, "domains")
        if "expires_at" not in cols:
            op.add_column("domains", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        if "accent" not in cols:
            op.add_column("domains", sa.Column("accent", sa.String(9), nullable=True))
        if "logo_data" not in cols:
            op.add_column("domains", sa.Column("logo_data", sa.Text(), nullable=True))

    # --- workspace_invites: shareable join links
    if "workspace_invites" not in insp.get_table_names():
        op.create_table(
            "workspace_invites",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token", sa.String(64), nullable=False, unique=True),
            sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_workspace_invites_workspace_id", "workspace_invites", ["workspace_id"])
        op.create_index("ix_workspace_invites_token", "workspace_invites", ["token"], unique=True)
        op.create_index("ix_workspace_invites_created_by", "workspace_invites", ["created_by"])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "workspace_invites" in insp.get_table_names():
        op.drop_table("workspace_invites")
    if "domains" in insp.get_table_names():
        cols = _columns(insp, "domains")
        for col in ("logo_data", "accent", "expires_at"):
            if col in cols:
                op.drop_column("domains", col)
