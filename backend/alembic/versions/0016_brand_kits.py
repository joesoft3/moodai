"""0016_brand_kits — 🧑‍💼 one-per-user brand identity for the Design Studio (v0.9.0)."""

import sqlalchemy as sa
from alembic import op

revision = "0016_brand_kits"
down_revision = "0015_designs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "brand_kits" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "brand_kits",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("brand_name", sa.String(120), server_default=""),
        sa.Column("tagline", sa.String(200), server_default=""),
        sa.Column("color_primary", sa.String(9), server_default=""),
        sa.Column("color_secondary", sa.String(9), server_default=""),
        sa.Column("color_accent", sa.String(9), server_default=""),
        sa.Column("font_vibe", sa.String(16), server_default="modern"),
        sa.Column("logo_design_id", sa.String(36), server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "brand_kits" in sa.inspect(bind).get_table_names():
        op.drop_table("brand_kits")
