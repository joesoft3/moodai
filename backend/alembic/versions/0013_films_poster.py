"""films.poster — hero-frame jpg for gallery tiles + share OG image (v0.6.0)

Revision ID: 0013_films_poster
Revises: 0012_films
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_films_poster"
down_revision = "0012_films"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("films")}
    if "poster" not in cols:
        op.add_column("films", sa.Column("poster", sa.String(44), nullable=False, server_default=""))


def downgrade():
    op.drop_column("films", "poster")
