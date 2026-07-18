"""0019_design_orders — 🛍 client-mode magic order links (v1.1.0)."""

import secrets

import sqlalchemy as sa
from alembic import op

revision = "0019_design_orders"
down_revision = "0018_edits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "design_orders" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "design_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(24), unique=True),
        sa.Column("status", sa.String(12), server_default="open"),
        sa.Column("customer_name", sa.String(80), server_default=""),
        sa.Column("idea", sa.Text, server_default=""),
        sa.Column("kind", sa.String(12), server_default="flyer"),
        sa.Column("style", sa.String(24), server_default="minimal"),
        sa.Column("design_id", sa.String(36), server_default=""),
        sa.Column("note", sa.String(200), server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_design_orders_owner_id", "design_orders", ["owner_id"])
    op.create_index("ix_design_orders_token", "design_orders", ["token"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    if "design_orders" in sa.inspect(bind).get_table_names():
        op.drop_table("design_orders")
