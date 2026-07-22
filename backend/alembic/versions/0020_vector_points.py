"""0020_vector_points — 🧠 pgvector store: memory/recall/doc-RAG move into Postgres.

One table, one row per semantic "point" (memory fact, chat digest, or doc chunk).
pgvector is a Neon trusted extension, so no new infra anywhere — the store also
lazy-self-heals in services/vectorstore.py for hosts that skip alembic (serverless).
"""

import sqlalchemy as sa
from alembic import op

from app.config import settings

revision = "0020_vector_points"
down_revision = "0019_design_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "vector_points" in sa.inspect(bind).get_table_names():
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"""
        CREATE TABLE vector_points (
            collection text NOT NULL,
            id text NOT NULL,
            embedding vector({int(settings.EMBED_VECTOR_SIZE)}),
            payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (collection, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS vector_points_user_idx "
        "ON vector_points (collection, ((payload->>'user_id')))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vector_points")
