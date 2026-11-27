"""Canonical job record shared by every source adapter.

Adapters return this shape; provenance, status, matching and the store only ever
see canonical records, so a new source (Jora, a careers page) is just a new adapter.

Field          Meaning
-------------  ------------------------------------------------------------
xid            "<source>:<external id>" primary external identifier, or None
src            Display source: Seek | Jora | Indeed | LinkedIn | Careers page
ext_id         Source's own job id (string) or None
u              Canonical job URL (tracking params stripped)
u_orig         URL exactly as received (preserved)
t              Job title
co / cn        Company key (data.json style) / display name
adv            Advertiser (recruiter or employer) display name
adv_id         Advertiser id if given
loc            "Suburb, City STATE" display string
place          {suburb, city, area, state, country, postcode}
sal            {min, max, cur, per, text, ann_min, ann_max} or None
cls            {cat, sub}
wt             Work type, e.g. "Full time"
wa             Work arrangement list, e.g. ["On-site"]
desc           Plain-text description (from description_text or html)
has_html       True if description_html was supplied
listed         Listing date (ISO)
exp_at         expires_at (ISO) / expired_at: actual expiry stamp (ISO)
flags          Source booleans, e.g. {"is_expired": True}
raw_keys       Top-level keys seen (for provenance / debugging, no values)
"""

FIELDS = (
    "xid", "src", "ext_id", "u", "u_orig", "t", "co", "cn", "adv", "adv_id",
    "loc", "place", "sal", "cls", "wt", "wa", "desc", "has_html", "listed",
    "exp_at", "expired_at", "flags", "raw_keys",
)


def blank():
    return {k: None for k in FIELDS} | {"place": {}, "cls": {}, "wa": [], "flags": {}, "raw_keys": []}
