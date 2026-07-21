"""v1.4.1 — DATABASE_URL normalization for hosted Postgres pastes (Neon/Aiven/Supabase)."""

from app.config import Settings


def _s(url):
    return Settings(_env_file=None, DATABASE_URL=url).DATABASE_URL


def test_legacy_postgres_scheme():
    assert _s("postgres://u:p@h:5432/db").startswith("postgresql+asyncpg://")


def test_modern_postgresql_scheme():
    assert _s("postgresql://u:p@h:5432/db").startswith("postgresql+asyncpg://")


def test_neon_style_sslmode_translated():
    out = _s("postgresql://u:p@ep-x-pooler.eu.aws.neon.tech/db?sslmode=require&channel_binding=require")
    assert out == "postgresql+asyncpg://u:p@ep-x-pooler.eu.aws.neon.tech/db?ssl=require"


def test_sslmode_verify_variants():
    assert "ssl=require" in _s("postgresql://u:p@h/db?sslmode=verify-full")
    assert "ssl=require" in _s("postgresql://u:p@h/db?sslmode=verify-ca")


def test_sslmode_disable_dropped():
    out = _s("postgresql://u:p@h/db?sslmode=disable")
    assert "sslmode" not in out and "ssl=" not in out


def test_other_query_params_preserved():
    out = _s("postgresql://u:p@h/db?options=-c%20search_path%3Dapp&sslmode=require")
    assert "ssl=require" in out and "options=-c%20search_path%3Dapp" in out


def test_sqlite_untouched():
    out = _s("sqlite+aiosqlite:////tmp/x.db")
    assert out == "sqlite+aiosqlite:////tmp/x.db"


def test_already_asyncpg_idempotent():
    out = _s("postgresql+asyncpg://u:p@h/db?sslmode=require")
    assert out.count("+asyncpg") == 1 and "ssl=require" in out
