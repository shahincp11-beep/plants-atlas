"""Job status: active | expired | closed | unavailable | unknown.

Rules (in order):
1. Expiry evidence (expired_at <= now, is_expired flag, expires_at <= now) -> expired.
   Nothing can promote an expired job back to active (a re-list is a new job id).
2. Authorised verification (alert email, Shahin's own check, employer JSON-LD):
   closed -> closed; gone/not_found/removed -> unavailable; live within VERIFY_DAYS -> active.
3. No fresh verification: active only if trust >= medium, expires_at is in the future
   and the listing is <= STALE_DAYS old. Otherwise unknown.
"""
from datetime import timedelta

from .util import parse_dt, now_utc, iso
from .provenance import RANK

STATUSES = ("active", "expired", "closed", "unavailable", "unknown")
VERIFY_DAYS = 7
STALE_DAYS = 45


def resolve(job, prov, verification=None, now=None):
    now = now or now_utc()
    ev = []
    exp, expd, listed = (parse_dt(job.get(k)) for k in ("exp_at", "expired_at", "listed"))
    flags = job.get("flags") or {}

    if expd and expd <= now:
        ev.append(f"expired_at {iso(expd)}")
    if flags.get("is_expired") is True:
        ev.append("is_expired flag")
    if exp and exp <= now:
        ev.append(f"expires_at {iso(exp)} passed")
    if flags.get("is_active") is False:
        ev.append("is_active=false")
    if ev:
        v = (verification or {}).get("state")
        if v == "live":
            ev.append("verification said live but expiry wins (never active once expired)")
        return {"st": "expired", "ver": bool(verification), "ev": ev}

    if flags.get("is_closed") is True:
        return {"st": "closed", "ver": False, "ev": ["is_closed flag"]}

    if verification:
        state, at = verification.get("state"), parse_dt(verification.get("at")) or now
        via = verification.get("via", "?")
        if state == "closed":
            return {"st": "closed", "ver": True, "ev": [f"closed per {via} {iso(at)}"]}
        if state in ("gone", "not_found", "removed", "unavailable"):
            return {"st": "unavailable", "ver": True, "ev": [f"{state} per {via} {iso(at)}"]}
        if state == "live" and now - at <= timedelta(days=VERIFY_DAYS):
            return {"st": "active", "ver": True, "ev": [f"live per {via} {iso(at)}"]}
        if state == "live":
            ev.append(f"last verified live {iso(at)} (older than {VERIFY_DAYS} d)")

    trust = (prov or {}).get("trust", "low")
    if RANK.get(trust, 0) < RANK["medium"]:
        return {"st": "unknown", "ver": False, "ev": ev + [f"trust {trust}: needs verification"]}
    if not exp:
        return {"st": "unknown", "ver": False, "ev": ev + ["no expires_at"]}
    if listed and now - listed > timedelta(days=STALE_DAYS):
        return {"st": "unknown", "ver": False, "ev": ev + [f"listed over {STALE_DAYS} d ago"]}
    return {"st": "active", "ver": False, "ev": ev + [f"expires {iso(exp)}, unverified"]}
