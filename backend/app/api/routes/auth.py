from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import create_access_token, hash_password, verify_password
from ...db.models import User
from ...db.session import get_db
from ...schemas import LoginRequest, PreferencesUpdate, RegisterRequest, TokenResponse
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


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == req.email.lower()))
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return TokenResponse(access_token=create_access_token(user.id), user=user_out(user))


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return user_out(user)


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
