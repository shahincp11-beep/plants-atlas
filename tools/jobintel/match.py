"""Explainable job-vs-profile scoring. Each dimension 0-100; hard exclusions force overall 0."""
import json
import os
import re

_HERE = os.path.dirname(__file__)


def load_profile(path=None):
    with open(path or os.path.join(_HERE, "profile.json"), encoding="utf-8") as f:
        return json.load(f)


def _has(text, term):
    term = term.strip()
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def _hits(text, terms):
    return [t for t in terms if _has(text, t)]


def exclusions(job, P):
    x = P["exclude"]
    title = (job.get("t") or "").lower()
    desc = (job.get("desc") or "").lower()
    cls = " ".join((job.get("cls") or {}).values()).lower()
    loc = " ".join([job.get("loc") or ""] + list((job.get("place") or {}).values())).lower()
    out = []
    # 'mechanical and electrical' titles stay in; only a title led by an excluded discipline is out
    mech = _has(title, "mechanical")
    for t in x["title"]:
        if _has(title, t) and not (mech and t in ("electrical", "instrumentation", "controls", "civil", "structural")):
            out.append(f"title: {t.strip()}")
    for t in x["anywhere"]:
        if _has(title, t) or _has(desc, t):
            out.append(f"excluded: {t}")
    for t in x["classification"]:
        if t in cls:
            out.append(f"classification: {t}")
    for t in x["location"]:
        if _has(loc, t):
            out.append(f"location: {t}")
    for t in x["work_rights"]:
        if _has(desc, t):
            out.append(f"work rights: {t}")
    return out


def tech(job, P):
    title = (job.get("t") or "").lower()
    text = f"{title}\n{(job.get('desc') or '').lower()}"
    core = _hits(title, P["roles"]["core"])
    sec = _hits(title, P["roles"]["secondary"])
    strong = _hits(text, P["skills"]["strong"])
    nice = _hits(text, P["skills"]["nice"])
    role = 45 if core else 30 if sec else 15 if _has(title, "engineer") else 0
    s = role + min(45, len(strong) * 5) + min(10, len(nice) * 2)
    if _has(text, "mechanical"):
        s += 5
    why = (core or sec or ["no target title"])[:1] + strong[:4]
    return min(100, s), why


def experience(job, P):
    title = (job.get("t") or "").lower()
    desc = (job.get("desc") or "").lower()
    yrs = [int(m) for m in re.findall(r"(\d{1,2})\s*\+?\s*(?:-\s*\d+\s*)?years?", desc) if 0 < int(m) < 30]
    need = max(yrs) if yrs else None
    s, why = 75, []
    if need is not None:
        gap = P["years"] - need
        s = 95 if 0 <= gap <= 7 else 70 if gap > 7 else max(20, 95 + gap * 15)
        why.append(f"asks {need}+ yrs")
    if re.search(r"\b(senior|lead|principal)\b", title):
        s = min(100, s + 5); why.append("senior level")
    if re.search(r"\b(junior|entry|assistant)\b", title):
        s -= 30; why.append("junior level")
    if re.search(r"\bmanager\b", title):
        s -= 10; why.append("manager title")
    return max(0, min(100, s)), why


def industry(job, P):
    text = " ".join([job.get("t") or "", job.get("cn") or "", job.get("desc") or "",
                     " ".join((job.get("cls") or {}).values())]).lower()
    for score, terms in P["sectors"]:
        h = _hits(text, terms)
        if h:
            return score, h[:2]
    return 40, ["sector unclear"]


def location(job, P):
    loc = " ".join([job.get("loc") or ""] + [str(v) for v in (job.get("place") or {}).values()]).lower()
    if any("remote" in w.lower() or "work from home" in w.lower() for w in job.get("wa") or []):
        return 60, ["remote/WFH"]
    for score, terms in P["locations"]:
        h = _hits(loc, terms)
        if h:
            return score, h[:1]
    if re.search(r"\b(nsw|new south wales)\b", loc):
        return 60, ["NSW other"]
    if re.search(r"\b(vic|victoria|qld|queensland)\b", loc):
        return 50, ["interstate other"]
    return (35, ["outside targets"]) if loc.strip() else (50, ["location unknown"])


def salary(job, P):
    s = job.get("sal") or {}
    lo, hi = s.get("ann_min"), s.get("ann_max") or s.get("ann_min")
    if not (lo or hi):
        return 55, ["salary not shown"], False
    lo = lo or hi
    f, t = P["salary"]["floor"], P["salary"]["target"]
    if hi < f * 0.9:
        return 10, [f"${hi:,.0f} below floor"], True
    if hi < f:
        return 35, [f"${hi:,.0f} just under floor"], True
    if hi >= t:
        return 100 if lo >= f else 90, [f"${lo:,.0f}-${hi:,.0f}"], True
    return 70, [f"${lo:,.0f}-${hi:,.0f} under target"], True


def employment(job, P):
    wt = (job.get("wt") or "").lower()
    desc = (job.get("desc") or "").lower()
    s, why = 80, []
    if "full" in wt or "permanent" in wt:
        s = 95; why.append("full time")
    elif "contract" in wt or "temp" in wt:
        s = 65; why.append("contract/temp")
    elif "part" in wt or "casual" in wt:
        s = 30; why.append("part time/casual")
    if re.search(r"\b(citizen(ship)?|baseline clearance|security clearance)\b", desc):
        s -= 15; why.append("check work-rights/clearance")
    if re.search(r"\b(rotating roster|night shift|on[- ]call|12[- ]hour)\b", desc):
        s -= 5; why.append("shift/on-call")
    return max(0, min(100, s)), why


def score(job, P=None):
    P = P or load_profile()
    w = P["weights"]
    t, tw = tech(job, P)
    e, ew = experience(job, P)
    i, iw = industry(job, P)
    l, lw = location(job, P)
    s, sw, has_sal = salary(job, P)
    m, mw = employment(job, P)
    overall = t * w["tech"] + e * w["exp"] + i * w["ind"] + l * w["loc"] + s * w["sal"] + m * w["emp"]
    cn = (job.get("cn") or "").lower()
    pri = any(_has(cn, p) for p in P["priority_employers"])
    if pri:
        overall += 5
    ex = exclusions(job, P)
    overall = 0 if ex else round(min(100, overall))
    b = P["bands"]
    band = "excluded" if ex else "high" if overall >= b["high"] else "good" if overall >= b["good"] else "fair" if overall >= b["fair"] else "low"
    return {"tech": t, "exp": e, "ind": i, "loc": l, "sal": s, "emp": m, "overall": overall, "band": band,
            "x": ex, "pri": pri, "has_sal": has_sal,
            "why": {"tech": tw, "exp": ew, "ind": iw, "loc": lw, "sal": sw, "emp": mw}}
