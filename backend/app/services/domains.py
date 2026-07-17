"""Custom domains: DNS verification (connect-your-own) and a registrar client for
real-time domain search + purchase (GoDaddy; OTE sandbox by default so the full
flow is testable without charging real money — flip GODADDY_ENV=production to go live).
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import settings

log = logging.getLogger(__name__)

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)


class DomainError(Exception):
    pass


class RegistrarNotConfigured(Exception):
    pass


def clean_domain(raw: str) -> str:
    d = raw.strip().lower().rstrip(".")
    d = re.sub(r"^https?://", "", d).split("/")[0]
    if not DOMAIN_RE.match(d):
        raise DomainError("That doesn't look like a valid domain (e.g. chat.mybusiness.com).")
    return d


def price_with_markup(cost_cents: int) -> int:
    return round(cost_cents * (1 + settings.DOMAIN_MARKUP_PCT / 100))


# --------------------------------------------------------------------- DNS checks
def _sync_txt_records(name: str) -> list[str]:
    import dns.resolver

    try:
        answers = dns.resolver.resolve(name, "TXT", lifetime=6)
        out = []
        for r in answers:
            try:
                out.append("".join(s.decode() if isinstance(s, bytes) else str(s) for s in r.strings))
            except AttributeError:
                out.append(str(r).strip('"'))
        return out
    except Exception:
        return []


def _sync_cname_records(name: str) -> list[str]:
    import dns.resolver

    try:
        answers = dns.resolver.resolve(name, "CNAME", lifetime=6)
        return [str(r.target).rstrip(".").lower() for r in answers]
    except Exception:
        return []


async def verify_txt(domain: str, token: str) -> bool:
    """TXT record _mood-verify.<domain> must contain our verification token."""
    records = await asyncio.to_thread(_sync_txt_records, f"_mood-verify.{domain}")
    return any(token in r for r in records)


async def cname_points(domain: str, target: str) -> bool:
    """Does <domain> (or www.<domain> for apex) CNAME to the platform target?"""
    target = target.rstrip(".").lower()
    for name in (domain, f"www.{domain}"):
        if target in await asyncio.to_thread(_sync_cname_records, name):
            return True
    return False


# --------------------------------------------------------------------- Registrar (GoDaddy)
class GoDaddyClient:
    BASE = {"ote": "https://api.ote-godaddy.com", "production": "https://api.godaddy.com"}

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=45.0))

    @property
    def configured(self) -> bool:
        return bool(settings.GODADDY_API_KEY and settings.GODADDY_API_SECRET)

    def _headers(self) -> dict:
        if not self.configured:
            raise RegistrarNotConfigured(
                "Registrar not configured — set GODADDY_API_KEY/SECRET (developer.godaddy.com/keys)."
            )
        return {
            "Authorization": f"sso-key {settings.GODADDY_API_KEY}:{settings.GODADDY_API_SECRET}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @property
    def _base(self) -> str:
        return self.BASE.get(settings.GODADDY_ENV, self.BASE["ote"])

    def _check(self, name: str, r: httpx.Response) -> Any:
        if r.status_code >= 400:
            raise DomainError(f"{name} failed ({r.status_code}): {r.text[:240]}")
        return r.json() if r.content else {}

    async def availability(self, domain: str) -> dict:
        r = await self._http.get(
            f"{self._base}/v1/domains/available", headers=self._headers(), params={"domain": domain, "checkType": "FULL"}
        )
        j = self._check("availability", r)
        # price is given in micro-units of currency
        price_micro = j.get("price") or 0
        return {
            "domain": domain,
            "available": bool(j.get("available")),
            "cost_cents": round(price_micro / 10_000),  # micros → cents
            "currency": j.get("currency", "USD"),
        }

    async def suggest(self, query: str, limit: int = 6) -> list[str]:
        r = await self._http.get(
            f"{self._base}/v1/domains/suggest", headers=self._headers(), params={"query": query, "limit": limit}
        )
        j = self._check("suggest", r)
        return [s for s in j if isinstance(s, str)][:limit]

    async def agreements(self, tld: str) -> list[dict]:
        r = await self._http.get(
            f"{self._base}/v1/domains/agreements", headers=self._headers(),
            params={"tlds": tld, "privacy": "true", "forTransfer": "false"},
        )
        j = self._check("agreements", r)
        return j if isinstance(j, list) else []

    async def purchase(self, domain: str, contact: dict, years: int) -> dict:
        tld = domain.rsplit(".", 1)[-1]
        agreements = await self.agreements(tld)
        body = {
            "domain": domain,
            "consent": {
                "agreementKeys": [a.get("agreementKey") for a in agreements if a.get("agreementKey")],
                "agreedBy": contact.get("email", "owner"),
                "agreedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            },
            "contactRegistrant": contact,
            "contactAdmin": contact,
            "contactTech": contact,
            "contactBilling": contact,
            "period": years,
            "privacy": True,
            "renewAuto": True,
            "nameServers": None,  # keep registrar defaults
        }
        r = await self._http.post(f"{self._base}/v1/domains/purchase", headers=self._headers(), json=body)
        return self._check("purchase", r)

    async def point_to_platform(self, domain: str) -> None:
        """Route a freshly purchased domain at the platform: apex A (if configured) + www CNAME."""
        ops: list[tuple[str, str, dict]] = []
        if settings.PLATFORM_CNAME_TARGET:
            ops.append(
                ("PUT", "replace", {"name": "www", "data": settings.PLATFORM_CNAME_TARGET.rstrip("."), "ttl": 3600})
            )
        if settings.PLATFORM_A_RECORD_IP:
            ops.append(("PUT", "replace", {"name": "@", "data": settings.PLATFORM_A_RECORD_IP, "ttl": 3600}))
        for method, _, rec in ops:
            r = await self._http.put(
                f"{self._base}/v1/domains/{domain}/records/{'CNAME' if rec['name'] == 'www' else 'A'}/{rec['name']}",
                headers=self._headers(),
                json=[{"data": rec["data"], "ttl": rec["ttl"], "name": rec["name"], "type": "CNAME" if rec["name"] == "www" else "A"}],
            )
            if r.status_code >= 400:
                log.warning("point_to_platform %s %s failed (%s): %s", domain, rec["name"], r.status_code, r.text[:160])


    async def get_domain(self, domain: str) -> dict:
        """Registrar-side details: expires (ISO), renewAuto, status, …"""
        r = await self._http.get(f"{self._base}/v1/domains/{domain}", headers=self._headers())
        return self._check("get_domain", r)

    async def set_auto_renew(self, domain: str, flag: bool) -> None:
        r = await self._http.patch(
            f"{self._base}/v1/domains/{domain}", headers=self._headers(), json={"renewAuto": flag}
        )
        self._check("set_auto_renew", r)

    async def renew(self, domain: str, years: int) -> dict:
        """Extend registration at the registrar (charges the platform's reseller account)."""
        r = await self._http.post(
            f"{self._base}/v1/domains/{domain}/renew",
            headers=self._headers(),
            json={"period": years},
        )
        return self._check("renew", r)


registrar = GoDaddyClient()


def parse_expiry(raw: Any) -> datetime | None:
    """Registrar returns ISO-8601 like 2027-07-16T23:59:59Z → aware datetime."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# --------------------------------------------------------------------- expiry watchdog
async def sync_expirations() -> int:
    """Pull expiry/auto-renew from the registrar for purchased domains that are
    stale (unknown expiry, or expiring within 90 days). Returns rows updated."""
    from sqlalchemy import or_, select

    from ..db.models import Domain
    from ..db.session import SessionLocal

    if not registrar.configured:
        return 0
    updated = 0
    try:
        now = datetime.now(timezone.utc)
        async with SessionLocal() as s:
            rows = (
                await s.execute(
                    select(Domain).where(
                        Domain.kind == "purchased",
                        Domain.registrar == "godaddy",
                        or_(Domain.expires_at.is_(None), Domain.status == "active"),
                    )
                )
            ).scalars().all()
            for d in rows:
                # skip fresh rows far from expiry
                if d.expires_at and (d.expires_at - now).days > 90:
                    continue
                try:
                    info = await registrar.get_domain(d.domain)
                except Exception as e:
                    log.warning("expiry sync %s failed: %s", d.domain, e)
                    continue
                exp = parse_expiry(info.get("expires"))
                if exp:
                    d.expires_at = exp
                if "renewAuto" in info:
                    d.auto_renew = bool(info.get("renewAuto"))
                updated += 1
            if updated:
                await s.commit()
    except Exception as e:
        log.warning("expiry sync cycle failed: %s", e)
    await _send_renewal_reminders()
    return updated


async def _send_renewal_reminders() -> None:
    """Owner reminder (via their connected Gmail, best-effort) when a purchased domain
    is inside the renewal window AND registrar auto-renew is OFF. Once per expiry date
    — Redis dedup key includes the expiry, so next year's window reminds again."""
    try:
        from sqlalchemy import select

        from ..api.deps import get_redis
        from ..db.models import Domain, User
        from ..db.session import SessionLocal
        from .notify import send_email

        window = max(7, settings.DOMAIN_RENEW_WINDOW_DAYS)
        now = datetime.now(timezone.utc)
        r = await get_redis()
        async with SessionLocal() as s:
            due = (
                await s.execute(
                    select(Domain).where(
                        Domain.kind == "purchased",
                        Domain.status == "active",
                        Domain.auto_renew.is_(False),
                        Domain.expires_at.is_not(None),
                    )
                )
            ).scalars().all()
            for d in due:
                if not d.expires_at:
                    continue
                days = (d.expires_at - now).days
                if days < 0 or days > window:
                    continue
                dedup = f"domrenew:{d.id}:{d.expires_at.strftime('%Y%m%d')}"
                try:
                    if await r.get(dedup):
                        continue
                    owner = await s.get(User, d.user_id)
                    if not owner:
                        continue
                    link = f"{settings.FRONTEND_URL}/settings"
                    ok = await send_email(
                        s,
                        owner.id,
                        owner.email,
                        f"⏳ Your domain {d.domain} expires in {days} day(s)",
                        (
                            f"Hi {owner.display_name or 'there'},\n\n"
                            f"Your domain {d.domain} expires on {d.expires_at.date().isoformat()} "
                            f"and registrar auto-renew is OFF.\n\n"
                            f"Renew it in one click: {link} (Custom domains → 🔁 Renew now).\n\n"
                            f"— Mood AI"
                        ),
                    )
                    if ok:
                        await r.set(dedup, "1", ex=45 * 86400)
                        log.info("renewal reminder sent for %s (%dd left)", d.domain, days)
                except Exception as e:
                    log.warning("renewal reminder failed for %s: %s", d.domain, e)
    except Exception as e:
        log.warning("renewal reminder pass failed: %s", e)


async def expiry_watchdog() -> None:
    """Background task: keep registrar expiry dates fresh (daily by default)."""
    import asyncio

    await asyncio.sleep(90)  # let the stack settle after startup
    while True:
        n = await sync_expirations()
        if n:
            log.info("domain expiry watchdog refreshed %d domain(s)", n)
        await asyncio.sleep(max(1, settings.DOMAIN_SYNC_HOURS) * 3600)


# --------------------------------------------------------------------- Vercel attach (optional)
async def vercel_attach(domain: str) -> bool:
    """Attach a verified custom domain to the hosting project (Vercel), best-effort."""
    if not (settings.VERCEL_API_TOKEN and settings.VERCEL_PROJECT_ID):
        return False
    async with httpx.AsyncClient(timeout=10) as h:
        params = {"teamId": settings.VERCEL_TEAM_ID} if settings.VERCEL_TEAM_ID else {}
        r = await h.post(
            f"https://api.vercel.com/v10/projects/{settings.VERCEL_PROJECT_ID}/domains",
            headers={"Authorization": f"Bearer {settings.VERCEL_API_TOKEN}"},
            params=params,
            json={"name": domain},
        )
        if r.status_code >= 400:
            log.warning("vercel attach %s failed: %s", domain, r.text[:160])
            return False
    return True
