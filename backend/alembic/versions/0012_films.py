"""films table — async storyboard rendering (v0.5.0)

Revision ID: 0012_films
Revises: 0011_devices
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_films"
down_revision = "0011_devices"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "films" not in insp.get_table_names():
        op.create_table(
            "films",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
            sa.Column("scenes_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(16), nullable=False, server_default="rendering"),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("scene_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("scene_seconds", sa.Integer(), nullable=False, server_default="6"),
            sa.Column("aspect", sa.String(8), nullable=False, server_default="16:9"),
            sa.Column("quality", sa.String(8), nullable=False, server_default="720p"),
            sa.Column("style", sa.String(40), nullable=False, server_default="cinematic"),
            sa.Column("audio", sa.String(20), nullable=False, server_default="none"),
            sa.Column("voice_id", sa.String(20), nullable=False, server_default="alloy"),
            sa.Column("music", sa.String(12), nullable=False, server_default="soft"),
            sa.Column("tempo", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("subtitles", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("filename", sa.String(40), nullable=False, server_default=""),
            sa.Column("fallback_url", sa.String(600), nullable=False, server_default=""),
            sa.Column("script", sa.Text(), nullable=False, server_default=""),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_films_user_id", "films", ["user_id"])
        op.create_index("ix_films_status", "films", ["status"])


def downgrade():
    op.drop_table("films")
