"""devices table — FCM push notifications (Phase 1)

Revision ID: 0011_devices
Revises: 0010_domain_arena
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_devices"
down_revision = "0010_domain_arena"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "devices" not in insp.get_table_names():
        op.create_table(
            "devices",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token", sa.String(255), nullable=False),
            sa.Column("platform", sa.String(16), nullable=False, server_default="android"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("token", name="uq_devices_token"),
        )
        op.create_index("ix_devices_user_id", "devices", ["user_id"])
        op.create_index("ix_devices_token", "devices", ["token"], unique=True)


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "devices" in insp.get_table_names():
        op.drop_index("ix_devices_token", table_name="devices")
        op.drop_index("ix_devices_user_id", table_name="devices")
        op.drop_table("devices")
