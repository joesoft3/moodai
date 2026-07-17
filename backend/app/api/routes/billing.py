"""Stripe subscriptions: checkout session, webhook, status. 503s gracefully when unconfigured."""

import asyncio
import logging
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import Subscription, User
from ...db.session import get_db
from ..deps import get_current_user

router = APIRouter()
log = logging.getLogger(__name__)


def _require_stripe() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing not configured — set STRIPE_* env vars")
    stripe.api_key = settings.STRIPE_SECRET_KEY


@router.post("/checkout")
async def create_checkout(user: User = Depends(get_current_user)):
    _require_stripe()
    if not settings.STRIPE_PRICE_ID:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Set STRIPE_PRICE_ID")
    session = await asyncio.to_thread(
        stripe.checkout.Session.create,
        mode="subscription",
        line_items=[{"price": settings.STRIPE_PRICE_ID, "quantity": 1}],
        customer_email=user.email,
        success_url=f"{settings.FRONTEND_URL}/chat?billing=success",
        cancel_url=f"{settings.FRONTEND_URL}/chat?billing=cancelled",
        metadata={"user_id": user.id},
    )
    return {"checkout_url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    _require_stripe()
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Webhook signature failed: {e}")

    etype = event["type"]
    obj = event["data"]["object"]

    async def upsert(user_id: str, **fields):
        sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id))
        if not sub:
            sub = Subscription(user_id=user_id)
            db.add(sub)
        for k, v in fields.items():
            setattr(sub, k, v)
        await db.commit()

    if etype == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        if meta.get("type") == "domain_purchase" and meta.get("domain_id"):
            from .domains import fulfill_domain_purchase

            await fulfill_domain_purchase(meta["domain_id"])  # buy at registrar + point DNS
        elif meta.get("type") == "domain_renewal" and meta.get("domain_id"):
            from .domains import fulfill_domain_renewal

            await fulfill_domain_renewal(meta["domain_id"], int(meta.get("years", 1)))  # extend at registrar
        else:
            user_id = meta.get("user_id")
            if user_id:
                await upsert(
                    user_id,
                    stripe_customer_id=obj.get("customer"),
                    stripe_subscription_id=obj.get("subscription"),
                    status="active",
                )
    elif etype in ("customer.subscription.updated", "customer.subscription.deleted"):
        sub = await db.scalar(
            select(Subscription).where(Subscription.stripe_customer_id == obj.get("customer"))
        )
        if sub:
            sub.status = "canceled" if etype.endswith("deleted") else obj.get("status", sub.status)
            epoch = obj.get("current_period_end")
            if epoch:
                sub.current_period_end = datetime.fromtimestamp(epoch, tz=timezone.utc)
            await db.commit()
    else:
        log.info("unhandled stripe event: %s", etype)
    return {"received": True}


@router.get("/status")
async def billing_status(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    return {
        "plan": user.plan,
        "subscription": sub.status if sub else "none",
        "current_period_end": sub.current_period_end.isoformat() if sub and sub.current_period_end else None,
    }
