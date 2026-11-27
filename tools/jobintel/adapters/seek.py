"""SEEK job JSON -> canonical record.

Tolerates snake_case and camelCase, strings or nested objects, and missing/null
fields. Never raises on odd input: unparseable parts are simply left None.
"""
import re

from ..model import blank
from ..util import (get, label, labels, parse_dt, iso, html_to_text,
                    canonical_url, co_key)

NAME = "seek"
DISPLAY = "Seek"
HOSTS = ("seek.com.au", "www.seek.com.au", "seek.co.nz", "www.seek.co.nz")

PER = {"annual": "year", "annually": "year", "year": "year", "yearly": "year",
       "hour": "hour", "hourly": "hour", "day": "day", "daily": "day",
       "month": "month", "monthly": "month", "week": "week", "weekly": "week"}
MULT = {"year": 1, "hour": 38 * 52, "day": 5 * 52, "week": 52, "month": 12}


def detect(obj):
    if not isinstance(obj, dict):
        return False
    u = str(get(obj, "url", "job_url", "jobUrl", "link", default=""))
    if "seek.com" in u:
        return True
    return bool(get(obj, "advertiser")) and bool(get(obj, "classification", "work_type", "workType"))


def _money(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).lower().replace(",", "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(k)?", s)
    if not m:
        return None
    x = float(m.group(1))
    return x * 1000 if m.group(2) else x


def parse_salary(raw):
    """Accepts {label,min,max,currency,period|type} or a plain string like '$130k - $150k + super'."""
    if raw in (None, "", {}):
        return None
    text = label(raw) if not isinstance(raw, dict) else (raw.get("label") or raw.get("text") or raw.get("display"))
    lo = hi = None
    cur = per = None
    if isinstance(raw, dict):
        lo = _money(get(raw, "min", "minimum", "from", "range.min", "minValue"))
        hi = _money(get(raw, "max", "maximum", "to", "range.max", "maxValue"))
        cur = label(get(raw, "currency", "currencyLabel"))
        per = label(get(raw, "period", "type", "unit", "frequency"))
    if text and (lo is None and hi is None):
        nums = [_money(x) for x in re.findall(r"\$?\s*\d[\d,]*(?:\.\d+)?\s*k?", text, re.I)]
        nums = [n for n in nums if n and n >= 15]  # ignore '11.5% super', '38 hrs'
        if nums:
            lo, hi = nums[0], (nums[1] if len(nums) > 1 else None)
    if not per and text:
        t = text.lower()
        per = ("hour" if re.search(r"per hour|/ ?h(ou)?r|p/?h\b|hourly", t) else
               "day" if re.search(r"per day|daily|/ ?day", t) else
               "year" if re.search(r"per (annum|year)|p\.?a\.?|annual|\bk\b|package|super", t) else None)
    pl = (per or "").strip().lower()
    per = PER.get(pl) or next((v for k, v in PER.items() if k in pl), None) or (
        "year" if (lo or hi or 0) >= 20000 else ("hour" if (lo or hi) else None))
    if lo and hi and lo > hi:
        lo, hi = hi, lo
    if lo is None and hi is None and not text:
        return None
    m = MULT.get(per or "", 1)
    return {"min": lo, "max": hi, "cur": cur or ("AUD" if text and "$" in text else None),
            "per": per, "text": text,
            "ann_min": round(lo * m) if lo else None, "ann_max": round(hi * m) if hi else None}


def _place(obj):
    loc = get(obj, "location", "joblocation", "jobLocation", default=None)
    p = {}
    if isinstance(loc, dict):
        p = {
            "suburb": label(get(loc, "suburb", "locality")),
            "city": label(get(loc, "city", "location", "area", "region")),
            "area": label(get(loc, "area")),
            "state": label(get(loc, "state", "stateCode", "state_code", "countryRegion")),
            "country": label(get(loc, "country", "countryCode", "country_code")),
            "postcode": label(get(loc, "postcode", "postalCode")),
            "label": label(get(loc, "label", "displayLabel", "description")),
        }
    elif isinstance(loc, list) and loc:
        return _place({"location": loc[0]})
    elif isinstance(loc, str):
        p = {"label": loc}
    for k, alt in (("suburb", "suburb"), ("city", "city"), ("state", "state"), ("area", "area")):
        p[k] = p.get(k) or label(obj.get(alt))
    return {k: v for k, v in p.items() if v}


def _loc_text(p):
    if p.get("label") and not p.get("city"):
        return p["label"]
    parts = [x for x in (p.get("suburb"), p.get("city") or p.get("area")) if x]
    s = ", ".join(dict.fromkeys(parts))
    if p.get("state"):
        s = f"{s} {p['state']}".strip()
    return s or p.get("label")


def parse(obj):
    j = blank()
    if not isinstance(obj, dict):
        return j
    j["raw_keys"] = sorted(obj.keys())[:60]
    j["src"] = DISPLAY
    u = get(obj, "url", "job_url", "jobUrl", "link", "share_link")
    j["u_orig"] = u
    j["u"] = canonical_url(u)
    eid = get(obj, "id", "job_id", "jobId", "listing_id", "listingId")
    if eid is None and j["u"]:
        m = re.search(r"/job/(\d+)", j["u"])
        eid = m.group(1) if m else None
    j["ext_id"] = str(eid).strip() if eid not in (None, "") else None
    j["xid"] = f"seek:{j['ext_id']}" if j["ext_id"] else None
    if not j["u"] and j["ext_id"] and j["ext_id"].isdigit():
        j["u"] = f"https://www.seek.com.au/job/{j['ext_id']}"

    j["t"] = label(get(obj, "title", "job_title", "jobTitle", "position"))
    comp = get(obj, "company", "companyName", "company_name", "employer")
    adv = get(obj, "advertiser", "advertiserName", "advertiser_name")
    j["cn"] = label(comp) or label(get(obj, "company_profile.name", "companyProfile.name")) or label(adv)
    j["adv"] = label(adv)
    j["adv_id"] = label(get(obj, "advertiser.id", "advertiserId", "advertiser_id"))
    j["co"] = co_key(j["cn"]) if j["cn"] else None

    j["place"] = _place(obj)
    j["loc"] = _loc_text(j["place"])
    j["sal"] = parse_salary(get(obj, "salary", "salary_label", "salaryLabel", "salary_range", "salaryRange", "compensation"))

    cls = get(obj, "classification", "classifications")
    sub = get(obj, "subclassification", "sub_classification", "subClassification", "classification.subclassification",
              "classification.sub_classification", "classification.subClassification")
    if isinstance(cls, list) and cls:
        sub = sub or get(cls[0], "subclassification", "subClassification")
        cls = cls[0]
    j["cls"] = {k: v for k, v in {"cat": label(get(cls, "description", "name", "label") if isinstance(cls, dict) else cls),
                                  "sub": label(sub)}.items() if v}

    j["wt"] = label(get(obj, "work_type", "workType", "workTypes", "work_types", "employmentType"))
    j["wa"] = labels(get(obj, "work_arrangement", "workArrangement", "workArrangements", "work_arrangements"))

    dh = get(obj, "description_html", "descriptionHtml", "content", "jobDescriptionHtml")
    dt = get(obj, "description_text", "descriptionText", "description", "teaser")
    j["has_html"] = bool(dh) and isinstance(dh, str)
    if isinstance(dt, str) and "<" in dt and ">" in dt:
        dt = html_to_text(dt)
    j["desc"] = (dt if isinstance(dt, str) and dt.strip() else html_to_text(dh)) or ""
    bullets = labels(get(obj, "bullet_points", "bulletPoints"))
    if bullets:
        j["desc"] = (j["desc"] + "\n" + "\n".join(bullets)).strip()

    j["listed"] = iso(parse_dt(get(obj, "listed_at", "listedAt", "listing_date", "listingDate", "posted_at", "postedAt", "datePosted", "created_at")))
    j["exp_at"] = iso(parse_dt(get(obj, "expires_at", "expiresAt", "expiry_date", "expiryDate", "validThrough", "expiry.expires_at", "expiry.at")))
    j["expired_at"] = iso(parse_dt(get(obj, "expired_at", "expiredAt", "expiry.expired_at", "closed_at", "closedAt")))
    flags = {}
    for k in ("is_expired", "isExpired", "expired", "is_active", "isActive", "is_closed", "isClosed"):
        if isinstance(obj.get(k), bool):
            flags[re.sub(r"(?<!^)([A-Z])", r"_\1", k).lower()] = obj[k]
    exp = obj.get("expiry")
    if isinstance(exp, dict) and isinstance(exp.get("is_expired"), bool):
        flags["is_expired"] = exp["is_expired"]
    j["flags"] = flags
    return j
