"""Job intelligence engine: raw JSON -> adapter -> provenance -> status -> match -> store."""
import json

from .adapters import get_adapter
from .provenance import check, RANK
from .status import resolve
from .match import score, load_profile
from .store import Store, fingerprint, level
from .util import parse_dt, now_utc, iso, day, h


def iter_records(payload):
    """Accept one object, a list, {jobs|data|results|items:[...]}, or NDJSON text."""
    if isinstance(payload, str):
        s = payload.strip()
        try:
            return iter_records(json.loads(s))
        except json.JSONDecodeError:
            out = []
            for line in s.splitlines():
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        out.append({"_unparseable": line[:80]})
            return out
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("jobs", "data", "results", "items", "listings"):
            if isinstance(payload.get(k), list):
                return payload[k]
        return [payload]
    return []


def to_record(j, prov, st, m, keep_desc=0):
    """Canonical -> data.json job (existing keys kept compatible, new keys added)."""
    s = j.get("sal") or {}
    rec = {
        "co": j.get("co"), "cn": j.get("cn"), "t": j.get("t"), "loc": j.get("loc"),
        "d": day(parse_dt(j.get("listed"))), "u": j.get("u"), "lvl": level(j.get("t")), "src": j.get("src"),
        "sum": {"sal": s.get("text")} if s.get("text") else ({"sal": f"${s['ann_min']:,}-{s['ann_max']:,}"} if s.get("ann_min") and s.get("ann_max") else None),
        "xid": j.get("xid"), "eid": j.get("ext_id"), "uo": j.get("u_orig") if j.get("u_orig") != j.get("u") else None,
        "adv": j.get("adv") if j.get("adv") != j.get("cn") else None,
        "sal": {k: s.get(k) for k in ("ann_min", "ann_max", "per")} if (s.get("ann_min") or s.get("ann_max")) else None,
        "cls": j.get("cls") or None, "wt": j.get("wt"), "wa": j.get("wa") or None,
        "la": j.get("listed"), "exp": j.get("exp_at"), "xa": j.get("expired_at"), "fl": j.get("flags") or None,
        "st": st["st"], "ver": st["ver"], "sev": st["ev"][:3],
        "m": {"o": m["overall"], "b": m["band"], "t": m["tech"], "e": m["exp"], "i": m["ind"], "l": m["loc"],
              "s": m["sal"], "p": m["emp"], "x": m["x"] or None, "pri": m["pri"] or None},
        "prov": {"tr": prov["trust"], "me": prov["method"], "at": prov["received_at"], "w": prov["warnings"][:3] or None},
        "fp": fingerprint(j.get("cn") or j.get("co"), j.get("t"), j.get("loc")),
        "dh": h(j.get("desc") or "", 12) if j.get("desc") else None,
    }
    if keep_desc and j.get("desc"):
        rec["jd"] = j["desc"][:keep_desc]
    return {k: v for k, v in rec.items() if v not in (None, "", [], {})}


def ingest(payload, jobs, source=None, meta=None, verifications=None, now=None, profile=None, keep_desc=0):
    """Returns (jobs, report). `jobs` is mutated in place (data.json jobs[])."""
    now = now or now_utc()
    P = profile or load_profile()
    store = Store(jobs)
    rep = {"at": iso(now), "in": 0, "added": [], "updated": [], "seen": 0, "quarantined": [], "errors": []}
    for raw in iter_records(payload):
        rep["in"] += 1
        try:
            ad = get_adapter(source, raw) if source else get_adapter(None, raw)
            if not ad:
                rep["quarantined"].append({"why": ["unrecognised record shape"]})
                continue
            j = ad.parse(raw)
            prov = check(j, ad.NAME, meta, now)
            if prov["trust"] == "reject":
                rep["quarantined"].append({"xid": j.get("xid"), "t": j.get("t"), "why": prov["errors"]})
                continue
            v = (verifications or {}).get(j.get("xid")) or (verifications or {}).get(j.get("u"))
            if not v and prov["method"] in ("alert_email",) and RANK[prov["trust"]] >= RANK["high"]:
                v = {"state": "live", "at": prov["received_at"], "via": "alert_email"}
            st = resolve(j, prov, v, now)
            m = score(j, P)
            rec = to_record(j, prov, st, m, keep_desc)
            if v:
                rec["vf"] = {"state": v["state"], "at": iso(parse_dt(v.get("at")) or now), "via": v.get("via")}
            act, stored = store.upsert(rec, now)
            if act == "seen":
                rep["seen"] += 1
            else:
                rep[act].append({"xid": stored.get("xid"), "t": stored.get("t"), "cn": stored.get("cn"),
                                 "st": stored.get("st"), "o": stored["m"]["o"], "b": stored["m"]["b"]})
        except Exception as e:  # one bad record never stops the batch
            rep["errors"].append(f"{type(e).__name__}: {str(e)[:120]}")
    return store.jobs, rep


def refresh(jobs, now=None):
    """Re-evaluate status of stored records (dates move on). Returns list of changes."""
    now = now or now_utc()
    changes = []
    for r in jobs:
        if "st" not in r:
            continue  # legacy record, not managed by the engine yet
        j = {"exp_at": r.get("exp"), "expired_at": r.get("xa"), "listed": r.get("la"), "flags": r.get("fl") or {}}
        prov = {"trust": (r.get("prov") or {}).get("tr", "low")}
        st = resolve(j, prov, r.get("vf"), now)
        if r.get("st") == "expired":
            st["st"] = "expired"
        if st["st"] != r["st"]:
            r.setdefault("hist", []).append({"at": iso(now), "ch": [f"st: {r['st']} -> {st['st']}"]})
            changes.append((r.get("xid") or r.get("u"), r["st"], st["st"]))
            r["st"] = st["st"]
        r["sev"], r["ver"] = st["ev"][:3], st["ver"]
    return changes


def verify(jobs, key, state, via, at=None, now=None):
    """Record an authorised availability check (alert email, Shahin's own look, employer JSON-LD)."""
    now = now or now_utc()
    for r in jobs:
        if key in (r.get("xid"), r.get("u"), r.get("eid")):
            r["vf"] = {"state": state, "at": iso(parse_dt(at) or now), "via": via}
            return refresh([r], now)
    return None
