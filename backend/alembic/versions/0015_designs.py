"""0015_designs — 🎨 Design Studio tables (flyers, logos, banners)."""

import sqlalchemy as sa
from alembic import op

revision = "0015_designs"
down_revision = "0014_films_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "designs" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "designs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(12), server_default="flyer"),
        sa.Column("idea", sa.Text, server_default=""),
        sa.Column("brief", sa.Text, server_default=""),
        sa.Column("prompt", sa.Text, server_default=""),
        sa.Column("style", sa.String(24), server_default="minimal"),
        sa.Column("palette", sa.String(16), server_default="auto"),
        sa.Column("transparent", sa.Boolean, server_default=sa.false()),
        sa.Column("width", sa.Integer, server_default="0"),
        sa.Column("height", sa.Integer, server_default="0"),
        sa.Column("file", sa.String(44), server_default=""),
        sa.Column("print_file", sa.String(44), server_default=""),
        sa.Column("note", sa.Text, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_designs_user_id", "designs", ["user_id"])
    op.create_index("ix_designs_kind", "designs", ["kind"])


def downgrade() -> None:
    bind = op.get_bind()
    if "designs" in sa.inspect(bind).get_table_names():
        op.drop_table("designs")
