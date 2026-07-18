"""films.views — privacy-safe public share counter (v0.7.0)

Revision ID: 0014_films_views
Revises: 0013_films_poster
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0014_films_views"
down_revision = "0013_films_poster"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("films")}
    if "views" not in cols:
        op.add_column("films", sa.Column("views", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("films", "views")
