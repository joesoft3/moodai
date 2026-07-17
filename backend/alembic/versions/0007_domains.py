"""add domains table (custom domains: connect-own + registrar purchases)

Revision ID: 0007_domains
Revises: 0006_workspaces
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_domains"
down_revision = "0006_workspaces"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "domains" in insp.get_table_names():
        return
    op.create_table(
        "domains",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("domain", sa.String(253), nullable=False, unique=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="connected"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_dns"),
        sa.Column("verification_token", sa.String(64), nullable=False, server_default=""),
        sa.Column("registrar", sa.String(24), nullable=True),
        sa.Column("registrar_order_id", sa.String(80), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("years", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("price_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("brand_name", sa.String(80), nullable=True),
        sa.Column("contact", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_domains_user_id", "domains", ["user_id"])
    op.create_index("ix_domains_domain", "domains", ["domain"], unique=True)
    op.create_index("ix_domains_workspace_id", "domains", ["workspace_id"])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "domains" in insp.get_table_names():
        op.drop_table("domains")
