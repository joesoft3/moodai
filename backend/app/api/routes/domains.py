"""Custom domains: real-time availability search, connect-your-own with DNS
verification, in-app purchase via Stripe checkout → registrar, white-label brand
lookup for the frontend, and an unauthenticated `allowed` endpoint for Caddy
on-demand TLS."""

import logging
import re
import secrets

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import Domain, User
from ...db.session import SessionLocal, get_db
from ...schemas import ConnectDomainRequest, DomainRenewRequest, DomainUpdateRequest, PurchaseDomainRequest
from ...services.domain_stats import analytics as domain_analytics
from ...services.domains import (
    DomainError,
    RegistrarNotConfigured,
    clean_domain,
    cname_points,
    parse_expiry,
    price_with_markup,
    registrar,
    vercel_attach,
    verify_txt,
)
from ..deps import enforce_rate_limit, get_current_user
from .workspaces import membership_of

router = APIRouter()
log = logging.getLogger(__name__)

LOGO_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,[A-Za-z0-9+/=]+$")
JUDGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,59}$")  # model ids (grok-4, gemini-2.5-pro, …)
ARENA_PROVIDERS = {"xai", "openai", "gemini"}


def _out(d: Domain) -> dict:
    return {
        "id": d.id,
        "domain": d.domain,
        "kind": d.kind,
        "status": d.status,
        "brand_name": d.brand_name,
        "years": d.years,
        "price_cents": d.price_cents,
        "currency": d.currency,
        "auto_renew": d.auto_renew,
        "workspace_id": d.workspace_id,
        "expires_at": d.expires_at.isoformat() if d.expires_at else None,
        "accent": d.accent,
        "has_logo": bool(d.logo_data),
        "arena": {
            "enabled": bool(d.arena_enabled),
            "daily_cap": d.arena_daily_cap or 0,
            "brand": d.arena_brand,
            "judge": d.arena_judge,
            "panel": d.arena_panel or [],
        },
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "dns": (
            {
                "txt_name": f"_mood-verify.{d.domain}",
                "txt_value": d.verification_token,
                "cname_target": settings.PLATFORM_CNAME_TARGET,
            }
            if d.kind == "connected" and d.status == "pending_dns"
            else None
        ),
    }


async def _owned(db: AsyncSession, user: User, did: str) -> Domain:
    d = await db.get(Domain, did)
    if not d or d.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain not found")
    return d


# ---------------------------------------------------------------- capabilities
@router.get("/providers")
async def domain_providers(user: User = Depends(get_current_user)):
    """Which parts of the domains feature are live (drives the UI)."""
    return {
        "registrar": registrar.configured,
        "registrar_env": settings.GODADDY_ENV,
        "stripe": bool(settings.STRIPE_SECRET_KEY),
        "platform_cname": settings.PLATFORM_CNAME_TARGET,
        "vercel_attach": bool(settings.VERCEL_API_TOKEN and settings.VERCEL_PROJECT_ID),
        "markup_pct": settings.DOMAIN_MARKUP_PCT,
    }


@router.get("")
async def list_domains(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(select(Domain).where(Domain.user_id == user.id).order_by(Domain.created_at.desc()))
    ).scalars().all()
    return {"domains": [_out(d) for d in rows]}


# ---------------------------------------------------------------- real-time search
@router.get("/search")
async def search_domains(q: str = Query(..., min_length=2, max_length=60), user: User = Depends(get_current_user)):
    await enforce_rate_limit(f"domsearch:{user.id}", 20)
    try:
        base_q = clean_domain(q) if "." in q else q.strip().lower().replace(" ", "")
    except DomainError:
        base_q = q.strip().lower().replace(" ", "")
    try:
        exact = clean_domain(base_q if "." in base_q else f"{base_q}.com")
    except DomainError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    try:
        candidates = [exact]
        for s in await registrar.suggest(base_q, limit=5):
            if s != exact:
                candidates.append(s)
        results = []
        for cand in candidates[:6]:
            try:
                info = await registrar.availability(cand)
                results.append(
                    {
                        "domain": info["domain"],
                        "available": info["available"],
                        "cost_cents": info["cost_cents"],
                        "price_cents": price_with_markup(info["cost_cents"]) if info["available"] else None,
                        "currency": info["currency"],
                    }
                )
            except (DomainError, TypeError, KeyError):
                continue
        return {"query": base_q, "env": settings.GODADDY_ENV, "results": results}
    except RegistrarNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))


# ---------------------------------------------------------------- connect own domain
@router.post("/connect", status_code=201)
async def connect_domain(
    req: ConnectDomainRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        domain = clean_domain(req.domain)
    except DomainError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    if await db.scalar(select(Domain).where(Domain.domain == domain)):
        raise HTTPException(status.HTTP_409_CONFLICT, "That domain is already connected to Mood")
    d = Domain(
        user_id=user.id,
        workspace_id=req.workspace_id,
        domain=domain,
        kind="connected",
        status="pending_dns",
        verification_token=secrets.token_urlsafe(16),
        brand_name=(req.brand_name or "").strip() or None,
    )
    db.add(d)
    await db.commit()
    return _out(d)


@router.post("/{did}/verify")
async def verify_domain(did: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    d = await _owned(db, user, did)
    if d.status == "active":
        return _out(d)
    txt_ok = await verify_txt(d.domain, d.verification_token)
    cname_ok = bool(settings.PLATFORM_CNAME_TARGET) and await cname_points(d.domain, settings.PLATFORM_CNAME_TARGET)
    if txt_ok and (cname_ok or not settings.PLATFORM_CNAME_TARGET):
        d.status = "active"
        await db.commit()
        if await vercel_attach(d.domain):
            log.info("domain %s attached to Vercel project", d.domain)
        return _out(d)
    return {
        **_out(d),
        "checks": {
            "txt_verified": txt_ok,
            "cname_points": cname_ok,
            "hint": (
                "DNS changes can take a few minutes to propagate. "
                f"Add TXT {('_mood-verify.' + d.domain)} = {d.verification_token}"
                + (f" and CNAME {d.domain} → {settings.PLATFORM_CNAME_TARGET}." if settings.PLATFORM_CNAME_TARGET else ".")
            ),
        },
    }


@router.delete("/{did}")
async def delete_domain(did: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    d = await _owned(db, user, did)
    await db.delete(d)
    await db.commit()
    return {"deleted": d.domain}


# ---------------------------------------------------------------- manage: theme / renew / binding
@router.patch("/{did}")
async def update_domain(
    did: str, req: DomainUpdateRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Brand name, accent, logo, auto-renew (wired to the registrar), workspace gate binding.
    None = unchanged; "" clears brand/logo/workspace."""
    d = await _owned(db, user, did)
    if req.brand_name is not None:
        d.brand_name = req.brand_name.strip() or None
    if req.accent is not None:
        d.accent = req.accent.lower()
    if req.logo_data is not None:
        if req.logo_data == "":
            d.logo_data = None
        else:
            if len(req.logo_data) > 200_000 or not LOGO_RE.match(req.logo_data):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Logo must be a data:image/(png|jpeg|webp|gif);base64 URL under ~150 KB",
                )
            d.logo_data = req.logo_data
    if req.workspace_id is not None:
        if req.workspace_id == "":
            d.workspace_id = None
        else:
            m = await membership_of(db, req.workspace_id, user.id)
            if not m or m.role != "owner":
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Only workspace owners can bind a domain gate")
            d.workspace_id = req.workspace_id
    if req.auto_renew is not None and req.auto_renew != d.auto_renew:
        if d.kind == "purchased" and d.registrar == "godaddy":
            try:
                await registrar.set_auto_renew(d.domain, req.auto_renew)
            except RegistrarNotConfigured as e:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
            except DomainError as e:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
        d.auto_renew = req.auto_renew  # connected domains: stored as a reminder preference
    # ⚔️ white-label arena settings
    if req.arena_enabled is not None:
        d.arena_enabled = req.arena_enabled
    if req.arena_daily_cap is not None:
        d.arena_daily_cap = req.arena_daily_cap
    if req.arena_brand is not None:
        d.arena_brand = req.arena_brand.strip() or None
    if req.arena_judge is not None:
        judge = req.arena_judge.strip() or None
        if judge and not JUDGE_RE.match(judge):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Judge model id: letters, digits, . _ - / only")
        d.arena_judge = judge
    if req.arena_panel is not None:
        if not req.arena_panel:
            d.arena_panel = None
        else:
            panel: list[dict] = []
            for p in req.arena_panel[:6]:
                prov, model = str(p.get("provider", "")), str(p.get("model", "")).strip()
                if prov not in ARENA_PROVIDERS or not model or not JUDGE_RE.match(model):
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "Panel entries need provider (xai|openai|gemini) + a valid model id",
                    )
                panel.append({"provider": prov, "model": model[:60], "label": str(p.get("label") or model)[:60]})
            if len({(p["provider"], p["model"]) for p in panel}) != len(panel):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Panel entries must be unique provider+model pairs")
            d.arena_panel = panel
    await db.commit()
    return _out(d)


@router.post("/{did}/refresh")
async def refresh_domain(did: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Pull live expiry date + auto-renew state from the registrar (purchased domains)."""
    d = await _owned(db, user, did)
    if d.kind != "purchased" or d.registrar != "godaddy":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only registrar-purchased domains can be refreshed")
    try:
        info = await registrar.get_domain(d.domain)
    except RegistrarNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except DomainError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
    exp = parse_expiry(info.get("expires"))
    if exp:
        d.expires_at = exp
    if "renewAuto" in info:
        d.auto_renew = bool(info.get("renewAuto"))
    await db.commit()
    return _out(d)


@router.post("/{did}/renew")
async def renew_domain(
    did: str, req: DomainRenewRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Paid renewal: Stripe checkout now → the webhook renews at the registrar after
    payment clears (`fulfill_domain_renewal`). Price derives from the original
    marked-up per-year rate, so margins stay consistent."""
    await enforce_rate_limit(f"dombuy:{user.id}", 5)
    d = await _owned(db, user, did)
    if d.kind != "purchased" or d.registrar != "godaddy":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only registrar-purchased domains renew through Mood")
    if not registrar.configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Registrar not configured")
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Payments not configured — set STRIPE_SECRET_KEY")
    stripe.api_key = settings.STRIPE_SECRET_KEY
    per_year = max(1, round(d.price_cents / max(1, d.years)))  # already marked up at purchase time
    years = req.years
    price_cents = per_year * years

    import asyncio

    session = await asyncio.to_thread(
        stripe.checkout.Session.create,
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": d.currency.lower(),
                    "product_data": {
                        "name": f"Domain renewal: {d.domain}",
                        "description": f"+{years} year{'s' if years > 1 else ''} · extends the current expiry date",
                    },
                    "unit_amount": price_cents,
                },
                "quantity": 1,
            }
        ],
        customer_email=user.email,
        success_url=f"{settings.FRONTEND_URL}/settings?domain_renewal=success",
        cancel_url=f"{settings.FRONTEND_URL}/settings?domain_renewal=cancelled",
        metadata={"type": "domain_renewal", "domain_id": d.id, "years": str(years), "user_id": user.id},
    )
    return {"checkout_url": session.url, "price_cents": price_cents, "currency": d.currency}


async def fulfill_domain_renewal(domain_id: str, years: int) -> None:
    """Stripe webhook → payment cleared: extend registration at the registrar,
    then re-sync the expiry date so the dashboard shows the new date."""
    try:
        async with SessionLocal() as s:
            d = await s.get(Domain, domain_id)
            if not d or d.kind != "purchased":
                return
            await registrar.renew(d.domain, max(1, years))
            try:
                info = await registrar.get_domain(d.domain)
                exp = parse_expiry(info.get("expires"))
                if exp:
                    d.expires_at = exp
                if "renewAuto" in info:
                    d.auto_renew = bool(info.get("renewAuto"))
            except Exception as e:
                log.warning("post-renewal sync failed for %s: %s", d.domain, e)
            await s.commit()
            log.info("domain renewed: %s (+%dy)", d.domain, years)
    except Exception as e:
        log.exception("domain renewal fulfillment failed for %s: %s", domain_id, e)


@router.get("/{did}/analytics")
async def get_domain_analytics(
    did: str, days: int = Query(default=14, ge=1, le=40), format: str = Query(default="json", pattern="^(json|csv)$"),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Requests + unique users per day for this custom domain (Redis-backed, fail-open).
    `format=csv` downloads the same series as a spreadsheet-ready file."""
    d = await _owned(db, user, did)
    data = {"domain": d.domain, **(await domain_analytics(d.id, days))}
    if format == "csv":
        import csv
        import io

        from fastapi.responses import Response

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["day", "requests", "unique_users"])
        for p in data["days"]:
            w.writerow([p["day"], p["requests"], p["users"]])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="mood-domain-{d.domain}-{days}d.csv"'},
        )
    return data


# ---------------------------------------------------------------- purchase (Stripe → registrar)
@router.post("/purchase")
async def purchase_domain(
    req: PurchaseDomainRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Real purchase flow: Stripe checkout (cost + markup) first; the webhook
    performs the registrar purchase AFTER payment clears, then points DNS here."""
    await enforce_rate_limit(f"dombuy:{user.id}", 5)
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Payments not configured — set STRIPE_SECRET_KEY")
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        domain = clean_domain(req.domain)
    except DomainError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    if await db.scalar(select(Domain).where(Domain.domain == domain)):
        raise HTTPException(status.HTTP_409_CONFLICT, "That domain is already taken in Mood")
    try:
        info = await registrar.availability(domain)
    except RegistrarNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except DomainError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
    if not info["available"]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{domain} is not available")

    years = req.years
    price_cents = price_with_markup(info["cost_cents"] * years)

    d = Domain(
        user_id=user.id,
        workspace_id=req.workspace_id,
        domain=domain,
        kind="purchased",
        status="purchasing",
        years=years,
        price_cents=price_cents,
        currency=info["currency"],
        brand_name=(req.brand_name or "").strip() or None,
        contact=req.contact.model_dump(),
        registrar="godaddy",
    )
    db.add(d)
    await db.commit()

    import asyncio

    session = await asyncio.to_thread(
        stripe.checkout.Session.create,
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": info["currency"].lower(),
                    "product_data": {
                        "name": f"Domain registration: {domain}",
                        "description": f"{years} year{'s' if years > 1 else ''} · privacy included · auto-connected to Mood",
                    },
                    "unit_amount": price_cents,
                },
                "quantity": 1,
            }
        ],
        customer_email=user.email,
        success_url=f"{settings.FRONTEND_URL}/settings?domain_purchase=success",
        cancel_url=f"{settings.FRONTEND_URL}/settings?domain_purchase=cancelled",
        metadata={"type": "domain_purchase", "domain_id": d.id, "user_id": user.id},
    )
    return {"checkout_url": session.url, "price_cents": price_cents, "currency": info["currency"], "env": settings.GODADDY_ENV}


async def fulfill_domain_purchase(domain_id: str) -> None:
    """Called by the Stripe webhook after payment: buy at registrar + point DNS."""
    try:
        async with SessionLocal() as s:
            d = await s.get(Domain, domain_id)
            if not d or d.status != "purchasing":
                return
            order = await registrar.purchase(d.domain, d.contact or {}, d.years)
            d.registrar_order_id = str(order.get("orderId") or order.get("order_id") or "")
            try:
                await registrar.point_to_platform(d.domain)
            except Exception as e:  # DNS pointing is retryable; don't fail the purchase
                log.warning("point_to_platform failed for %s: %s", d.domain, e)
            try:  # seed the expiry date so the dashboard shows it immediately
                info = await registrar.get_domain(d.domain)
                d.expires_at = parse_expiry(info.get("expires")) or d.expires_at
            except Exception:
                pass
            d.status = "active"  # purchased domains are authoritative — no TXT check needed
            await s.commit()
            log.info("domain purchased & activated: %s (order %s)", d.domain, d.registrar_order_id)
            await vercel_attach(d.domain)
    except Exception as e:
        log.exception("domain purchase fulfillment failed for %s: %s", domain_id, e)
        async with SessionLocal() as s:
            d = await s.get(Domain, domain_id) if domain_id else None
            if d:
                d.status = "failed"
                await s.commit()


# ---------------------------------------------------------------- public: white-label + edge
@router.get("/by-host")
async def brand_by_host(host: str = Query(..., max_length=253), db: AsyncSession = Depends(get_db)):
    """White-label lookup used by the frontend shell: active domain → brand config."""
    try:
        domain = clean_domain(host.split(":")[0]) if host else ""
    except DomainError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no brand")
    d = await db.scalar(select(Domain).where(Domain.domain == domain, Domain.status == "active"))
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no brand")
    return {
        "domain": d.domain,
        "brand_name": d.brand_name or "Mood AI",
        "workspace_id": d.workspace_id,
        "accent": d.accent,
        "logo_data": d.logo_data,
        # ⚔️ public white-label arena surface (quotas/panel stay owner-only)
        "arena": {
            "enabled": bool(d.arena_enabled),
            "brand": (d.arena_brand or d.brand_name) if d.arena_enabled else None,
        },
    }


@router.get("/allowed")
async def domain_allowed(domain: str = Query(..., max_length=253), db: AsyncSession = Depends(get_db)):
    """Caddy on-demand TLS `ask` endpoint: 200 = issue the cert, 403 = refuse.

    Caddyfile snippet:
      tls { on_demand_tls { ask http://backend:8000/api/v1/domains/allowed?domain={domain} } }
    """
    try:
        d_name = clean_domain(domain)
    except DomainError:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    d = await db.scalar(select(Domain).where(Domain.domain == d_name, Domain.status == "active"))
    if not d:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    return {"allowed": True}
