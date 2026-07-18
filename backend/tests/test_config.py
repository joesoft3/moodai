"""Settings: hosting-safe DATABASE_URL normalization + parsing helpers."""

from app.config import Settings


def _s(**kw):
    kw.setdefault("_env_file", None)  # never pick up a stray local .env in CI
    return Settings(**kw)


def test_postgres_scheme_normalized_to_asyncpg():
    s = _s(DATABASE_URL="postgres://u:p@db.host:5432/mood")
    assert s.DATABASE_URL == "postgresql+asyncpg://u:p@db.host:5432/mood"


def test_postgresql_scheme_normalized_to_asyncpg():
    s = _s(DATABASE_URL="postgresql://u:p@db.host/mood")
    assert s.DATABASE_URL == "postgresql+asyncpg://u:p@db.host/mood"


def test_asyncpg_scheme_left_alone():
    s = _s(DATABASE_URL="postgresql+asyncpg://u:p@db.host/mood")
    assert s.DATABASE_URL == "postgresql+asyncpg://u:p@db.host/mood"


def test_other_schemes_untouched():
    s = _s(DATABASE_URL="sqlite:///./mood.db")
    assert s.DATABASE_URL == "sqlite:///./mood.db"


def test_cors_origin_list_parses_csv_and_strips():
    s = _s(CORS_ORIGINS="https://app.mood.ai, https://mood-ai.netlify.app , *")
    assert s.cors_origin_list == ["https://app.mood.ai", "https://mood-ai.netlify.app", "*"]


def test_cors_default_is_not_empty():
    defaults = _s()
    assert defaults.cors_origin_list  # at least localhost dev origin


def test_admin_email_set_lowercases_and_strips():
    s = _s(ADMIN_EMAILS="  Owner@Mood.AI , second@mood.ai ,")
    assert s.admin_email_set == {"owner@mood.ai", "second@mood.ai"}


def test_app_password_defaults_off():
    # The sign-up access-code gate must stay off on fresh deploys.
    assert _s().APP_PASSWORD == ""
