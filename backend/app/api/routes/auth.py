from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import create_access_token, hash_password, verify_password
from ...db.models import User
from ...db.session import get_db
from ...schemas import (AccountDeleteRequest, ClerkAuthRequest, LoginRequest, PasswordChangeRequest,
                         PreferencesUpdate, RegisterRequest, TokenResponse)
from ...services import account as account_svc
from ...services import clerk_auth
from ...services.platform_settings import app_password_hash, signup_open
from ..deps import get_current_user, is_effective_admin

router = APIRouter()


def user_out(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "plan": u.plan,
        "custom_instructions": u.custom_instructions,
        "is_admin": is_effective_admin(u),
    }


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Owner-controlled gates: invite-only mode and/or an app access password.
    if not await signup_open(db):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Signups are closed on this deployment — ask an owner for a team invite link.",
        )
    gate = await app_password_hash(db)
    if gate and not (req.app_password and verify_password(req.app_password, gate)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This app requires an access code to sign up — ask the owner."
        )
    exists = await db.scalar(select(User).where(User.email == req.email.lower()))
    if exists:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An account with this email already exists")
    user = User(
        email=req.email.lower(),
        hashed_password=hash_password(req.password),
        display_name=req.display_name,
        # first-ever admin env email registering becomes an owner automatically via require_admin
    )
    db.add(user)
    await db.commit()
    return TokenResponse(access_token=create_access_token(user.id), user=user_out(user))


@router.post("/clerk", response_model=TokenResponse)
async def clerk_login(req: ClerkAuthRequest, db: AsyncSession = Depends(get_db)):
    """🔐 Clerk federation (Phase 1): verify a Clerk session JWT, link the
    account by email (find-or-provision), and mint our standard token.
    Docs: docs/CLERK-AUTH-ASSESSMENT.md — disabled until CLERK_ISSUER is set.
    """
    if not clerk_auth.clerk_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clerk sign-in is not enabled on this deployment")
    import secrets as _secrets

    try:
        claims = await clerk_auth.verify_clerk_token(req.token)
        email = await clerk_auth.resolve_email(claims)
    except clerk_auth.ClerkTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Clerk token rejected: {e}")
    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Clerk account has no reachable email address")

    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        # New federated account — the same owner signup gates apply as /register.
        if not await signup_open(db):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Signups are closed on this deployment — ask an owner for a team invite link.",
            )
        if await app_password_hash(db):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "This deployment requires an access code — sign up with email instead."
            )
        user = User(
            email=email,
            hashed_password=hash_password(_secrets.token_urlsafe(32)),  # unusable; federated login only
            display_name=email.split("@")[0],
        )
        db.add(user)
        await db.commit()
    return TokenResponse(access_token=create_access_token(user.id), user=user_out(user))


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == req.email.lower()))
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return TokenResponse(access_token=create_access_token(user.id), user=user_out(user))


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.post("/change-password")
async def change_password(
    req: PasswordChangeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """🔑 Self-service password change — gated on the CURRENT password.

    Generating a strong password is a client convenience (Settings → Security
    ships a crypto-strength generator); the API enforces ≥8 chars, refuses a
    no-op rotation, and only rewrites the hash AFTER the current password
    verifies. Existing sessions stay signed in (stateless JWT) — log out of
    other devices manually if you suspect a leak. Server-side admins can also
    reset a user's password from the owner panel (no current password needed),
    but that path is for support recovery, not self-service.
    """
    if not verify_password(req.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password didn't match")
    if req.current_password == req.new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "New password must differ from the current one")
    # The dep-injected session may differ from the auth session — reattach.
    db_user = await db.get(User, user.id)
    if db_user is None:  # account deleted between token issue and now
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account no longer exists")
    db_user.hashed_password = hash_password(req.new_password)
    await db.commit()
    return {"ok": True, "message": "Password updated — this device stays signed in."}


@router.delete("/me")
async def delete_me(
    req: AccountDeleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """🗑 Permanent self-service account deletion (Play/App Store requirement).

    Password re-entry gates the red button; everything the user owns is erased
    — conversations, uploads, designs, films, edits, orders, memories (vector
    store), plugin tokens, devices; owned teams dissolve. No grace period, no
    recovery: the stores require real deletion, and so do we."""
    if not verify_password(req.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Password didn't match — account NOT deleted")
    summary = await account_svc.delete_user_data(db, user)
    return {"deleted": True, "summary": summary,
            "message": "Your Mood AI account and all associated data were permanently deleted."}


@router.patch("/preferences")
async def update_preferences(
    req: PreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Personalization: persistent custom instructions injected into every chat."""
    user.custom_instructions = (req.custom_instructions or "").strip() or None
    await db.commit()
    return user_out(user)
