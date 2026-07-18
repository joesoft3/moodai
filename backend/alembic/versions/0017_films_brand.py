"""0017_films_brand — ⭐ films carry optional brand identity (v1.0.0)."""

import sqlalchemy as sa
from alembic import op

revision = "0017_films_brand"
down_revision = "0016_brand_kits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("films")}
    if "brand_name" not in cols:
        op.add_column("films", sa.Column("brand_name", sa.String(80), server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("films")}
    if "brand_name" in cols:
        op.drop_column("films", "brand_name")
