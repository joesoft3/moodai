"""0018_edits — ✂️ auto video editor history (v1.1.0)."""

import sqlalchemy as sa
from alembic import op

revision = "0018_edits"
down_revision = "0017_films_brand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "edits" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "edits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instruction", sa.Text, server_default=""),
        sa.Column("plan_json", sa.Text, server_default="{}"),
        sa.Column("status", sa.String(16), server_default="rendering"),
        sa.Column("src_name", sa.String(48), server_default=""),
        sa.Column("out_name", sa.String(44), server_default=""),
        sa.Column("note", sa.Text, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_edits_user_id", "edits", ["user_id"])
    op.create_index("ix_edits_status", "edits", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    if "edits" in sa.inspect(bind).get_table_names():
        op.drop_table("edits")
