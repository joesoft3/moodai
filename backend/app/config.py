import os

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _asyncpg_url(cls, v):
        """Hosting platforms hand out postgres(ql):// DSNs — force the asyncpg driver."""
        if isinstance(v, str):
            if v.startswith("postgres://"):
                return "postgresql+asyncpg://" + v[len("postgres://"):]
            if v.startswith("postgresql://"):
                return "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    # Core
    APP_NAME: str = "Mood AI"
    DEBUG: bool = False
    DATABASE_URL: str = "postgresql+asyncpg://mood:mood@localhost:5432/mood"
    REDIS_URL: str = "redis://localhost:6379/0"
    QDRANT_URL: str = "http://localhost:6333"
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    UPLOAD_DIR: str = "./storage"       # auto-relocated to /tmp on serverless (see _serverless_relocate)
    MOOD_SERVERLESS: str = ""           # force "1" to emulate a serverless host locally
    MAX_UPLOAD_MB: int = 25
    MAX_AUDIO_UPLOAD_MB: int = 15  # music / spoken-word uploads for AI analysis
    MAX_VIDEO_UPLOAD_MB: int = 50  # mp4/mov uploads for scene-by-scene AI analysis
    VIDEO_ANALYSIS_FRAMES: int = 6  # frames sampled per video for vision captioning
    MAX_FILE_CHARS: int = 30_000
    CORS_ORIGINS: str = "http://localhost:3000"
    FRONTEND_URL: str = "http://localhost:3000"

    # xAI / Grok (OpenAI-compatible API)
    XAI_API_KEY: str = ""
    XAI_BASE_URL: str = "https://api.x.ai/v1"
    MODEL_CHAT: str = "grok-4"
    MODEL_FAST: str = "grok-3-mini"
    MODEL_VISION: str = "grok-2-vision-1212"
    MODEL_IMAGE: str = "grok-2-image-1212"
    MODEL_CHAT_FAST: str = "grok-4-fast"      # ⚡ premium picker fast tier
    MODEL_CODE: str = "grok-code-fast-1"      # 💻 premium picker coding tier
    THINK_TRACE_KEEP: int = 120               # 🧠 max reasoning deltas persisted per message

    # ⚔️ Arena (Pro feature) — panel models per provider
    ARENA_XAI_MODEL: str = ""          # default: MODEL_CHAT (grok-4) — also the judge
    ARENA_OPENAI_MODEL: str = "gpt-4o"
    ARENA_GEMINI_MODEL: str = "gemini-2.5-pro"
    ARENA_CODE_MODEL: str = "grok-code-fast-1"

    # LLM failover — while set, calls that would go to xAI (chat, picker tiers,
    # vision analysis, titles, memory) are answered by the stand-in provider
    # instead. Perfect for "xAI credits not purchased yet" or provider outages.
    # Unset both and the Grok primary stack resumes instantly.
    LLM_FALLBACK_PROVIDER: str = ""   # e.g. "gemini" (needs that provider's API key set)
    LLM_FALLBACK_MODEL: str = ""      # one model for all fallback calls, e.g. "gemini-2.5-flash"

    # Multi-provider router (any OpenAI-compatible endpoint; inactive until keys set)
    GEMINI_API_KEY: str = ""
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    # Route heavy tasks per provider: xai | gemini | openai (falls back to xai if unconfigured)
    PROVIDER_CHAT: str = "xai"
    PROVIDER_CODING: str = "xai"
    PROVIDER_AGENTS: str = "xai"
    PROVIDER_DEEPSEARCH: str = "xai"
    # Optional model overrides when routing away from xAI
    ROUTE_MODEL_CODING: str = ""      # e.g. gemini-2.5-pro | gpt-4o
    ROUTE_MODEL_AGENTS: str = ""
    ROUTE_MODEL_DEEPSEARCH: str = ""
    ROUTE_MODEL_CHAT: str = ""

    # Web search: "xai_live" (built in) or "tavily"
    SEARCH_PROVIDER: str = "xai_live"
    TAVILY_API_KEY: str = ""

    # Voice: Whisper STT + TTS (OpenAI-compatible; swap provider to taste)
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    WHISPER_MODEL: str = "whisper-1"
    TTS_MODEL: str = "tts-1"
    TTS_VOICE: str = "alloy"

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID: str = ""

    # Custom domains (connect own + real-time purchase for business white-label)
    PLATFORM_CNAME_TARGET: str = ""   # e.g. cname.mood-ai.app — users CNAME their domain here
    PLATFORM_A_RECORD_IP: str = ""    # apex IP for purchased domains (optional; www gets CNAME)
    DOMAIN_MARKUP_PCT: int = 20       # your margin on registrar cost price
    GODADDY_API_KEY: str = ""         # registrar integration (developer.godaddy.com/keys)
    GODADDY_API_SECRET: str = ""
    GODADDY_ENV: str = "ote"          # "ote" = sandbox testing · "production" = real purchases
    VERCEL_API_TOKEN: str = ""        # optional: auto-attach verified domains to your Vercel project
    VERCEL_PROJECT_ID: str = ""
    VERCEL_TEAM_ID: str = ""
    BASE_DOMAIN: str = ""             # platform's own host (skipped in per-domain analytics)
    DOMAIN_SYNC_HOURS: int = 24       # how often the watchdog refreshes registrar expiry dates
    DOMAIN_RENEW_WINDOW_DAYS: int = 30  # show "Renew now" / send reminder inside this window
    INVITE_TTL_DAYS: int = 7          # workspace invite link lifetime

    # App owner / admin panel
    ADMIN_EMAILS: str = ""            # comma-separated owner emails (always admin, in addition to users.is_admin)
    ADMIN_BOOTSTRAP_EMAIL: str = ""   # env-defined owner account (created/promoted at boot)
    ADMIN_BOOTSTRAP_PASSWORD: str = ""  # owner-only password for the bootstrap account
    APP_PASSWORD: str = ""            # optional sign-up access code seeded into the platform gate

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    # Memory / RAG
    MEMORY_COLLECTION: str = "user_memories"
    EMBED_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"  # local fastembed (skipped when not installed)
    EMBED_API_MODEL: str = "text-embedding-3-small"  # fallback over OPENAI_BASE_URL when fastembed absent
    EMBED_VECTOR_SIZE: int = 384
    MEMORY_TOP_K: int = 6

    # Cross-conversation recall (remembering previous chats)
    RECALL_TOP_K: int = 3           # semantically relevant past chats injected per message
    RECALL_MIN_SCORE: float = 0.38  # cosine threshold for past-chat recall
    RECENT_CHATS_DIGEST: int = 2    # most-recent chat summaries injected into brand-new conversations

    # Plugins (Gmail / Google Calendar / GitHub via OAuth)
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"  # OAuth callbacks point here
    PLUGIN_TOKEN_KEY: str = ""      # Fernet key; falls back to one derived from JWT_SECRET (dev)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    PLUGIN_MAX_CALLS: int = 4       # tool-call rounds per message

    # Push notifications (Phase 1: FCM HTTP v1 — docs/PUSH-NOTIFICATIONS.md)
    FCM_PROJECT_ID: str = ""
    FCM_SERVICE_ACCOUNT_JSON: str = ""  # entire service-account JSON as one env string
    NOTIFY_COOLDOWN_SECONDS: int = 300  # per user+kind, process-local

    # Video generation (provider seam: xai today; runway/pika as env becomes available)
    VIDEO_PROVIDER: str = "xai"
    MODEL_VIDEO: str = "grok-video-1"
    VIDEO_MAX_WAIT_SECONDS: int = 240
    # Cinema Sound: AI voiceover + ambience muxed onto generated video (ffmpeg)
    FFMPEG_PATH: str = "ffmpeg"
    MEDIA_DIR: str = "/tmp/mood-media"      # muxed videos served from /media/files/{name}
    MEDIA_TTL_HOURS: int = 24               # janitor purges muxed files older than this
    VIDEO_MAX_DOWNLOAD_MB: int = 256        # cap when pulling the provider clip for muxing

    # Code execution sandbox (built-in run_python_code tool)
    SANDBOX_ENABLED: bool = True    # NOT a hardened security boundary — see services/sandbox.py
    SANDBOX_TIMEOUT: int = 8        # seconds
    SANDBOX_MAX_OUTPUT: int = 6000  # chars captured from stdout/stderr each

    # Limits
    CHAT_RATE_LIMIT_PER_MIN: int = 30
    HISTORY_WINDOW: int = 20

    # Ops
    AUTO_CREATE_TABLES: bool = True  # dev convenience; prod: false + `alembic upgrade head`
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""  # e.g. http://jaeger:4318 to enable tracing

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def serverless(self) -> bool:
        """True when running on an ephemeral host (Vercel / AWS Lambda / forced via MOOD_SERVERLESS=1)."""
        return bool(
            self.MOOD_SERVERLESS == "1"
            or os.environ.get("VERCEL") == "1"
            or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        )

    @model_validator(mode="after")
    def _serverless_relocate(self):
        """Serverless filesystems are read-only except /tmp — move writable dirs there."""
        if self.serverless:
            if self.UPLOAD_DIR.rstrip("/") in ("./storage", "storage", ""):
                self.UPLOAD_DIR = "/tmp/mood-uploads"
            if not self.MEDIA_DIR.startswith("/tmp"):
                self.MEDIA_DIR = "/tmp/mood-media"
        return self


settings = Settings()
