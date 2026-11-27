"""Job store on top of data.json `jobs[]`. Dedup, merge with history, never deletes.

Dedup order: 1) xid (source:id)  2) canonical URL  3) company + title + location.
Key 3 never merges two different ids from the same source (possible re-list):
those stay separate and the newer one gets `dup` = older xid.
Application status (applied / rejected …) is NOT stored here: it stays in the vault.
"""
import re

from .util import canonical_url, norm, h, day, parse_dt, iso

HIST_MAX = 30
TRACKED = ("t", "loc", "st", "exp", "sal", "o")


def _state(loc):
    m = re.search(r"\b(NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\b", loc or "", re.I)
    return m.group(1).upper() if m else ""


def _city(loc):
    parts = [p.strip() for p in re.sub(r"\b(NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\b", "", loc or "", flags=re.I).split(",") if p.strip()]
    return norm(parts[-1]) if parts else ""


def fingerprint(co, t, loc):
    place = _state(loc) or _city(loc)
    return h(f"{norm(co)}|{norm(t)}|{place}") if (co and t) else None


def xid_of(rec):
    if rec.get("xid"):
        return rec["xid"]
    m = re.search(r"seek\.com\.au/job/(\d+)", rec.get("u") or "")
    return f"seek:{m.group(1)}" if m else None


def keys_of(rec):
    return (xid_of(rec), canonical_url(rec.get("u")), rec.get("fp") or fingerprint(rec.get("cn") or rec.get("co"), rec.get("t"), rec.get("loc")))


def level(t):
    t = (t or "").lower()
    if re.search(r"\b(manager|head)\b", t):
        return "Manager"
    if re.search(r"\b(lead|principal)\b", t):
        return "Lead"
    if re.search(r"\bsenior|\bsnr\b|\bsr\.?\b", t):
        return "Senior"
    if re.search(r"\b(junior|graduate|entry|assistant)\b", t):
        return "Junior"
    return "Mid"


class Store:
    def __init__(self, jobs):
        self.jobs = jobs if isinstance(jobs, list) else []
        self._reindex()

    def _reindex(self):
        self.by_x, self.by_u, self.by_f = {}, {}, {}
        for i, r in enumerate(self.jobs):
            x, u, f = keys_of(r)
            if x: self.by_x.setdefault(x, i)
            if u: self.by_u.setdefault(u, i)
            if f: self.by_f.setdefault(f, i)

    def find(self, x, u, f, src):
        if x and x in self.by_x:
            return self.by_x[x], "id"
        if u and u in self.by_u:
            return self.by_u[u], "url"
        if f and f in self.by_f:
            i = self.by_f[f]
            other = self.jobs[i]
            ox = xid_of(other)
            if x and ox and ox != x and ox.split(":")[0] == x.split(":")[0]:
                return None, f"relist:{ox}"
            return i, "co+title+loc"
        return None, None

    def upsert(self, rec, now):
        """rec: flat stored record (see engine.to_record). Returns (action, stored)."""
        x, u, f = keys_of(rec)
        i, how = self.find(x, u, f, rec.get("src"))
        at = iso(now)
        if i is None:
            rec["fs"] = rec["ls"] = at
            rec["hist"] = [{"at": at, "ch": ["new"] + ([f"possible re-list of {how[7:]}"] if how and how.startswith("relist") else [])}]
            if how and how.startswith("relist"):
                rec["dup"] = how[7:]
            self.jobs.append(rec)
            self._reindex()
            return "added", rec
        old = self.jobs[i]
        ch = []
        for k in TRACKED:
            a = old.get(k) if k != "o" else (old.get("m") or {}).get("o")
            b = rec.get(k) if k != "o" else (rec.get("m") or {}).get("o")
            if k == "sal":
                a, b = (old.get("sum") or {}).get("sal"), (rec.get("sum") or {}).get("sal")
            if b not in (None, "") and a != b:
                ch.append(f"{k}: {a} -> {b}" if k in ("st", "o") else k)
        # an expired record never goes back to active
        if old.get("st") == "expired" and rec.get("st") == "active":
            rec["st"] = "expired"
            ch = [c for c in ch if not c.startswith("st:")]
        keep = {k: old[k] for k in ("fs", "hist", "sf", "sw", "dup", "vf") if k in old}
        merged = dict(old)
        merged.update({k: v for k, v in rec.items() if v not in (None, "", [], {})})
        merged.update(keep)
        if old.get("xid") and rec.get("xid") and old["xid"] != rec["xid"]:
            merged["xid"] = old["xid"]
            merged.setdefault("alt", [])
            if rec["xid"] not in merged["alt"]:
                merged["alt"].append(rec["xid"])
        merged["ls"] = at
        if ch:
            merged["hist"] = (merged.get("hist") or []) + [{"at": at, "ch": ch, "via": how}]
            merged["hist"] = merged["hist"][-HIST_MAX:]
        self.jobs[i] = merged
        self._reindex()
        return ("updated" if ch else "seen"), merged
