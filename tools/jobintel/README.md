# jobintel — job intelligence engine

Stdlib-only Python and zero cost. Claude runs it during chats. It turns any source's JSON into one canonical job, checks provenance, sets status, scores the job against `profile.json`, and merges it into `data.json` without deleting anything.

```
raw JSON ─► adapters/<source>.py ─► provenance.py ─► status.py ─► match.py ─► store.py ─► data.json jobs[]
```

## Commands (run from the repo root)
```
python3 -m tools.jobintel score  job.json --source seek                    # dry run, prints a breakdown
python3 -m tools.jobintel ingest job.json --source seek --method user_supplied
python3 -m tools.jobintel refresh                                          # re-check expiry dates
python3 -m tools.jobintel verify seek:12345678 --state closed --via user_check
python3 -m tools.jobintel list --st active --band high
python3 -m unittest tools.jobintel.tests.test_engine
```
Input can be one object, a list, `{jobs|data|results|items:[…]}` or NDJSON.

## Provenance (`--method`)
| Method | Trust | Notes |
|---|---|---|
| `alert_email` | high | The email counts as a "live" check at its send time |
| `user_supplied` / `manual_entry` / `saved_export` | medium | Shahin pasted or exported it himself |
| `careers_page_jsonld` | high | The employer's own schema.org JobPosting |
| `unknown` | low | Stored, but can never be `active` until verified |
| `scrape`, `third_party_scrape`, `bulk_crawl` | reject | Quarantined and not stored |

A record is also rejected for a look-alike host, an ID that doesn't match its URL, a missing title, HTML in the title, or a listing date in the future. Sources and permissions live in `sources.json`.

## Status
`expired` (from `expired_at`, the `is_expired` flag, or a past `expires_at`) always wins, and an expired job never becomes `active` again. A verification of `closed` gives `closed`, and `gone` gives `unavailable`. A `live` check within 7 days gives `active`. Without a check, a job is `active` only when trust is medium or higher, `expires_at` is in the future and the listing is ≤ 45 days old. Everything else is `unknown`.

## Match (`m` on each job)
`t` technical · `e` experience · `i` industry · `l` location · `s` salary · `p` employment suitability · `o` overall · `b` band (high ≥ 75, good ≥ 60, fair ≥ 45, low, excluded) · `x` hard-exclusion reasons (these force `o` = 0) · `pri` priority employer (+5).

## Dedup
The engine matches on `xid` (`seek:<id>`) first, then the canonical URL, then a fingerprint of company + title + state. If two different IDs from the same source share a fingerprint, they're kept separate as a possible re-list (`dup`). A match from another source is merged, and its ID goes in `alt`. Changes are logged in `hist` (last 30). `fs`/`ls` are first-seen and last-seen.

## New fields on data.json jobs
`xid eid uo adv sal{ann_min,ann_max,per} cls wt wa la exp xa fl st ver sev vf m prov fp dh fs ls hist dup alt` (all optional; old records still work). Descriptions are not stored unless `--keep-desc N`.

## Dashboard filters (index.html, to build once approved)
| Filter | Field |
|---|---|
| Active / Expired / Closed / Unavailable / Unknown | `st` |
| High match | `m.b == "high"` |
| Excluded (engine) | `m.x` |
| Salary available | `sal.ann_min || sal.ann_max` |
| Location | `loc` (+ state) |
| Company | `co` / `cn` |
| Source | `src` (+ `alt` prefixes) |
| Applied / Rejected | the vault's `track[jid].s`, decrypted in the browser only. It is never written to data.json |

## Add a source
Create `adapters/<name>.py` with `NAME`, `DISPLAY`, `detect(obj)` and `parse(obj) -> canonical`. Then register it in `adapters/__init__.py` and `sources.json`. The JobPosting adapter already covers careers pages that publish JSON-LD. Jora needs its own adapter once a real sample is available.
