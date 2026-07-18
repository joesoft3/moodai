import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def uid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[str] = mapped_column(String(20), default="free")
    is_admin: Mapped[bool] = mapped_column(default=False)  # app-owner panel access (ADMIN_EMAILS env also grants)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class PlatformSetting(Base):
    """Key/value platform knobs owned by the app admin (app access gate, etc.)."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # owner | member
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )  # set → shared with all workspace members
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # rolling cross-chat recall summary
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )  # author of user messages (team chats); null = legacy / assistant
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class FileAsset(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(120))
    path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="inactive")
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageEvent(Base):
    """One metered API action (chat reply, agent run, image, …) for plan dashboards/limits."""

    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)  # chat | agent | deepsearch | voice | image
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    estimated: Mapped[bool] = mapped_column(default=False)  # True → token counts are heuristic, not provider-reported
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SharedLink(Base):
    """Public read-only link to a conversation (revocable)."""

    __tablename__ = "shared_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PluginConnection(Base):
    """Per-user OAuth connection to an external app (Gmail, Calendar, GitHub)."""

    __tablename__ = "plugin_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40))  # gmail | google_calendar | github
    account: Mapped[str | None] = mapped_column(String(255), nullable=True)  # email / login label
    access_token_enc: Mapped[str] = mapped_column(Text)  # Fernet-encrypted
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[str] = mapped_column(String(500), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingAction(Base):
    """A write tool call (send email, create event/issue) awaiting in-chat user approval."""

    __tablename__ = "pending_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tool: Mapped[str] = mapped_column(String(60))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected | failed
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Domain(Base):
    """Custom domain: connected (BYO, DNS-verified) or purchased in-app via registrar."""

    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    domain: Mapped[str] = mapped_column(String(253), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="connected")  # connected | purchased
    status: Mapped[str] = mapped_column(String(20), default="pending_dns")  # pending_dns | active | failed | purchasing
    verification_token: Mapped[str] = mapped_column(String(64), default="")
    registrar: Mapped[str | None] = mapped_column(String(24), nullable=True)  # godaddy | external
    registrar_order_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    auto_renew: Mapped[bool] = mapped_column(default=True)
    years: Mapped[int] = mapped_column(Integer, default=1)
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    brand_name: Mapped[str | None] = mapped_column(String(80), nullable=True)  # white-label name
    contact: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # registrant contact (purchased)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # registrar expiry (synced)
    accent: Mapped[str | None] = mapped_column(String(9), nullable=True)  # white-label accent hex, e.g. #7c9bff
    logo_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # small data-URL logo (white-label)
    # ⚔️ white-label arena (per-domain debates on the domain owner's branding)
    arena_enabled: Mapped[bool] = mapped_column(default=False)
    arena_daily_cap: Mapped[int] = mapped_column(Integer, default=0)  # 0 = fall back to the user's plan cap
    arena_brand: Mapped[str | None] = mapped_column(String(80), nullable=True)  # shown as the arena/judge name
    arena_judge: Mapped[str | None] = mapped_column(String(60), nullable=True)  # judge model id (xAI-routed)
    arena_panel: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{"provider","model","label"}] custom panel
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceInvite(Base):
    """Shareable join link for a workspace (optionally gated to a bound domain's email addresses)."""

    __tablename__ = "workspace_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Device(Base):
    """FCM push tokens — Phase 1 push notifications (see docs/PUSH-NOTIFICATIONS.md)."""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(16), default="android")  # android | ios | web
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Film(Base):
    """🎬 Storyboard films — async-rendered multi-scene movies (docs/VIDEO-SOUND.md).

    status: rendering → done | failed. progress tracks finished scene renders.
    filename points into MEDIA_DIR (24h TTL janitor); scenes_json keeps the
    shot/narration pairs (and lets users re-mix the film later)."""

    __tablename__ = "films"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    scenes_json: Mapped[str] = mapped_column(Text, default="[]")     # [{shot, narration}]
    status: Mapped[str] = mapped_column(String(16), default="rendering", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)        # scenes rendered
    scene_count: Mapped[int] = mapped_column(Integer, default=0)
    scene_seconds: Mapped[int] = mapped_column(Integer, default=6)
    aspect: Mapped[str] = mapped_column(String(8), default="16:9")
    quality: Mapped[str] = mapped_column(String(8), default="720p")
    style: Mapped[str] = mapped_column(String(40), default="cinematic")
    audio: Mapped[str] = mapped_column(String(20), default="none")   # none|voice|voice+ambience
    voice_id: Mapped[str] = mapped_column(String(20), default="alloy")
    music: Mapped[str] = mapped_column(String(12), default="soft")
    tempo: Mapped[float] = mapped_column(Float, default=1.0)
    subtitles: Mapped[bool] = mapped_column(Boolean, default=False)
    filename: Mapped[str] = mapped_column(String(40), default="")
    poster: Mapped[str] = mapped_column(String(44), default="")        # <uuid>_p.jpg hero frame
    views: Mapped[int] = mapped_column(Integer, default=0)             # 👁 public share-page opens
    fallback_url: Mapped[str] = mapped_column(String(600), default="")
    script: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Design(Base):
    """🎨 Design Studio — flyers, logos & banners with print-tier PNGs.

    `file` = web-tier PNG in MEDIA_DIR (<uuid>_d.png), `print_file` = 300-DPI
    lanczos-upscaled print tier (<uuid>_dp.png). `prompt` keeps the compiled
    art-director prompt so users can re-mix the design later."""

    __tablename__ = "designs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12), default="flyer", index=True)   # flyer|logo|banner
    idea: Mapped[str] = mapped_column(Text, default="")             # user's raw idea
    brief: Mapped[str] = mapped_column(Text, default="")            # art-director rewrite (if enhanced)
    prompt: Mapped[str] = mapped_column(Text, default="")           # compiled provider prompt
    style: Mapped[str] = mapped_column(String(24), default="minimal")
    palette: Mapped[str] = mapped_column(String(16), default="auto")
    transparent: Mapped[bool] = mapped_column(Boolean, default=False)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    file: Mapped[str] = mapped_column(String(44), default="")       # web tier png
    print_file: Mapped[str] = mapped_column(String(44), default="")  # 300-DPI print png
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
