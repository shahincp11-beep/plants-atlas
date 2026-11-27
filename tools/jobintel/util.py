"""Small shared helpers: safe getters, dates, text, URLs, fingerprints. Stdlib only."""
import hashlib
import html
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

TRACKING = re.compile(r"^(utm_|ref|tracking|token|sol|cid|gclid|fbclid|mc_|jobsource|origin)", re.I)


def get(obj, *paths, default=None):
    """First non-empty value among dotted paths, e.g. get(j, 'company.name', 'companyName')."""
    for p in paths:
        cur = obj
        for part in p.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
                cur = cur[int(part)]
            else:
                cur = None
            if cur is None:
                break
        if cur not in (None, "", [], {}):
            return cur
    return default


def label(v):
    """Turn str | {label|name|description|value} | list into a display string or None."""
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        for k in ("label", "name", "description", "displayName", "value", "text"):
            if v.get(k):
                return label(v[k])
        return None
    if isinstance(v, list):
        parts = [x for x in (label(i) for i in v) if x]
        return ", ".join(dict.fromkeys(parts)) or None
    return None


def labels(v):
    """Like label() but always returns a de-duplicated list."""
    if v is None:
        return []
    if isinstance(v, list):
        out = []
        for i in v:
            s = label(i)
            if s and s not in out:
                out.append(s)
        return out
    s = label(v)
    return [s] if s else []


def parse_dt(v):
    """ISO string / epoch s or ms / YYYY-MM-DD -> aware UTC datetime, else None."""
    if v in (None, "", 0):
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        x = float(v)
        if x > 1e12:
            x /= 1000
        try:
            return datetime.fromtimestamp(x, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(v, str):
        s = v.strip()
        if s.isdigit():
            return parse_dt(int(s))
        s = s.replace("Z", "+00:00")
        try:
            d = datetime.fromisoformat(s)
        except ValueError:
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
            if not m:
                return None
            d = datetime(int(m[1]), int(m[2]), int(m[3]))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return None


def iso(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def day(d):
    return d.strftime("%Y-%m-%d") if d else None


def now_utc():
    return datetime.now(timezone.utc)


_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr)\b[^>]*>", re.I)


def html_to_text(h):
    if not h or not isinstance(h, str):
        return ""
    t = _BLOCK.sub("\n", h)
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", t, flags=re.I | re.S)
    t = _TAG.sub(" ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def norm(s):
    """Lowercase, strip punctuation and legal suffixes for fingerprinting."""
    s = (s or "").lower()
    s = re.sub(r"&", " and ", s)
    s = re.sub(r"\b(pty|ltd|limited|inc|llc|plc|australia|aust|group|the)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def co_key(name):
    """Short lowercase company key in the style of data.json `co`."""
    n = norm(name)
    return n.replace(" ", "")[:24] if n else "unknown"


def canonical_url(u):
    if not u or not isinstance(u, str):
        return None
    u = u.strip()
    if not re.match(r"^https?://", u, re.I):
        return None
    p = urlsplit(u)
    host = p.netloc.lower().split("@")[-1]
    if host.endswith(":443") or host.endswith(":80"):
        host = host.rsplit(":", 1)[0]
    m = re.search(r"(?:^|\.)seek\.com\.au$", host) and re.search(r"/job/(\d+)", p.path)
    if m:
        return f"https://www.seek.com.au/job/{m.group(1)}"
    q = urlencode([(k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k)])
    path = re.sub(r"/+$", "", p.path) or "/"
    return urlunsplit(("https", host, path, q, ""))


def h(s, n=16):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:n]


def jid(url):
    """Same hash the app uses: h=7; h=(h*31+code)>>>0; base36."""
    x = 7
    for ch in url or "":
        x = (x * 31 + ord(ch)) & 0xFFFFFFFF
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        x, r = divmod(x, 36)
        out = digits[r] + out
        if x == 0:
            return out
