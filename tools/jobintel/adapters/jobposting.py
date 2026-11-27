"""schema.org JobPosting (JSON-LD on company careers pages, many boards incl. Jora) -> canonical."""
import re

from ..model import blank
from ..util import get, label, labels, parse_dt, iso, html_to_text, canonical_url, co_key
from .seek import parse_salary

NAME = "jobposting"
DISPLAY = "Careers page"


def detect(obj):
    t = obj.get("@type") if isinstance(obj, dict) else None
    return t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t)


def parse(obj, display=DISPLAY):
    j = blank()
    if not isinstance(obj, dict):
        return j
    j["raw_keys"] = sorted(obj.keys())[:60]
    j["src"] = display
    u = get(obj, "url", "sameAs")
    j["u_orig"], j["u"] = u, canonical_url(u)
    ident = obj.get("identifier")
    eid = label(get(ident, "value")) if isinstance(ident, dict) else label(ident)
    j["ext_id"] = eid
    host = re.sub(r"^www\.", "", (j["u"] or "").split("/")[2]) if j["u"] else "web"
    j["xid"] = f"{host}:{eid}" if eid else None
    j["t"] = label(obj.get("title"))
    j["cn"] = label(get(obj, "hiringOrganization.name", "hiringOrganization"))
    j["co"] = co_key(j["cn"]) if j["cn"] else None
    loc = obj.get("jobLocation")
    loc = loc[0] if isinstance(loc, list) and loc else loc
    a = get(loc, "address") if isinstance(loc, dict) else None
    a = a if isinstance(a, dict) else {}
    j["place"] = {k: v for k, v in {"suburb": label(a.get("addressLocality")), "state": label(a.get("addressRegion")),
                                    "country": label(a.get("addressCountry")), "postcode": label(a.get("postalCode"))}.items() if v}
    j["loc"] = " ".join(x for x in (j["place"].get("suburb"), j["place"].get("state")) if x) or None
    bs = obj.get("baseSalary")
    if isinstance(bs, dict):
        v = bs.get("value") if isinstance(bs.get("value"), dict) else {"value": bs.get("value")}
        j["sal"] = parse_salary({"min": get(v, "minValue", "value"), "max": get(v, "maxValue"),
                                 "currency": bs.get("currency"), "period": get(v, "unitText")})
    j["wt"] = label(obj.get("employmentType"))
    j["wa"] = ["Remote"] if obj.get("jobLocationType") == "TELECOMMUTE" else []
    d = obj.get("description") or ""
    j["has_html"] = "<" in d
    j["desc"] = html_to_text(d) if j["has_html"] else d
    j["listed"] = iso(parse_dt(obj.get("datePosted")))
    j["exp_at"] = iso(parse_dt(obj.get("validThrough")))
    j["cls"] = {k: v for k, v in {"cat": label(obj.get("industry")), "sub": label(obj.get("occupationalCategory"))}.items() if v}
    return j
