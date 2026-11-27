"""Provenance and permission checks. No record is trusted just because it arrived as JSON.

trust: high | medium | low | reject
  reject  -> quarantined, never stored as a job (blocked method, wrong host, no title, ID/URL mismatch)
  low     -> stored, but status can never be 'active' until verified
"""
import json
import os
import re
from datetime import timedelta

from .util import parse_dt, now_utc, iso

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "sources.json"), encoding="utf-8") as f:
    SOURCES = json.load(f)

RANK = {"reject": 0, "low": 1, "medium": 2, "high": 3}


def check(job, source, meta=None, now=None):
    """meta: {method, origin?, received_at?}. Returns {trust, method, checks:[...], errors:[...], warnings:[...]}."""
    now = now or now_utc()
    meta = meta or {}
    method = (meta.get("method") or "unknown").strip().lower()
    cfg = SOURCES.get(source, {})
    errors, warns, ok = [], [], []

    if not cfg:
        errors.append(f"source '{source}' not registered in sources.json")
    if method in cfg.get("blocked", []):
        errors.append(f"collection method '{method}' not permitted for {source}")
    trust = cfg.get("allowed", {}).get(method)
    if not trust and method not in cfg.get("blocked", []):
        warns.append(f"unknown collection method '{method}'")
        trust = "low"

    if not job.get("t"):
        errors.append("missing title")
    elif re.search(r"<[^>]+>", job["t"]):
        errors.append("HTML in title")
    if not (job.get("cn") or job.get("adv")):
        warns.append("missing company and advertiser")
    if not (job.get("ext_id") or job.get("u")):
        errors.append("no job id or URL")

    hosts = cfg.get("hosts") or []
    u = job.get("u") or ""
    if u and hosts:
        host = u.split("/")[2] if u.count("/") >= 2 else ""
        if host not in hosts:
            errors.append(f"URL host '{host}' is not {source}")
        else:
            ok.append("host")
    if job.get("ext_id") and cfg.get("id_pattern") and not re.match(cfg["id_pattern"], job["ext_id"]):
        errors.append("job id format invalid")
    if source == "seek" and job.get("ext_id") and job.get("u_orig"):
        m = re.search(r"/job/(\d+)", job["u_orig"])
        if m and m.group(1) != job["ext_id"]:
            errors.append("job id does not match URL")
        elif m:
            ok.append("id=url")

    listed, exp, expd = (parse_dt(job.get(k)) for k in ("listed", "exp_at", "expired_at"))
    if listed and listed > now + timedelta(days=1):
        errors.append("listing date in the future")
    if listed and listed < now - timedelta(days=730):
        warns.append("listing older than 2 years")
    if listed and exp and exp < listed:
        warns.append("expires before listed")
    if exp and listed and exp - listed > timedelta(days=400):
        warns.append("expiry implausibly far after listing")
    if expd and expd > now + timedelta(days=1):
        warns.append("expired_at in the future")
    rec = parse_dt(meta.get("received_at"))
    if rec and rec > now + timedelta(minutes=10):
        warns.append("received_at in the future")
    if not listed:
        warns.append("no listing date")
    s = job.get("sal") or {}
    if s.get("ann_min") and s["ann_min"] > 1_000_000:
        warns.append("salary implausible")
    if len(job.get("desc") or "") < 80:
        warns.append("description missing or very short")

    if errors:
        trust = "reject"
    elif trust == "high" and len(warns) >= 2:
        trust = "medium"
    elif trust == "medium" and len(warns) >= 3:
        trust = "low"
    return {"trust": trust, "method": method, "origin": meta.get("origin"),
            "received_at": iso(rec) if rec else iso(now), "checked_at": iso(now),
            "ok": ok, "warnings": warns, "errors": errors}
