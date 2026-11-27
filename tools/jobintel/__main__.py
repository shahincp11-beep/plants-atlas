"""CLI (run from repo root):

  python3 -m tools.jobintel ingest FILE.json --method user_supplied [--source seek] [--db data.json] [--dry-run]
  python3 -m tools.jobintel refresh [--db data.json] [--dry-run]
  python3 -m tools.jobintel verify KEY --state live|closed|gone --via alert_email|user_check [--db data.json]
  python3 -m tools.jobintel score FILE.json [--source seek]          # no writes
  python3 -m tools.jobintel list [--st active] [--band high] [--db data.json]

Output is a short summary only (never prints descriptions or whole files).
"""
import argparse
import json
import sys

from .engine import ingest, refresh, verify, iter_records
from .adapters import get_adapter
from .provenance import check
from .status import resolve
from .match import score


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save(p, data):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jobintel")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ingest"); a.add_argument("file"); a.add_argument("--source"); a.add_argument("--method", default="unknown")
    a.add_argument("--origin"); a.add_argument("--received-at"); a.add_argument("--db", default="data.json")
    a.add_argument("--dry-run", action="store_true"); a.add_argument("--keep-desc", type=int, default=0)
    r = sub.add_parser("refresh"); r.add_argument("--db", default="data.json"); r.add_argument("--dry-run", action="store_true")
    v = sub.add_parser("verify"); v.add_argument("key"); v.add_argument("--state", required=True, choices=["live", "closed", "gone"])
    v.add_argument("--via", required=True); v.add_argument("--at"); v.add_argument("--db", default="data.json")
    s = sub.add_parser("score"); s.add_argument("file"); s.add_argument("--source"); s.add_argument("--method", default="user_supplied")
    l = sub.add_parser("list"); l.add_argument("--db", default="data.json"); l.add_argument("--st"); l.add_argument("--band"); l.add_argument("-n", type=int, default=15)
    o = ap.parse_args(argv)

    if o.cmd == "score":
        with open(o.file, encoding="utf-8") as f:
            recs = iter_records(f.read())
        for raw in recs:
            ad = get_adapter(o.source, raw)
            if not ad:
                print("? unrecognised record"); continue
            j = ad.parse(raw); pv = check(j, ad.NAME, {"method": o.method}); st = resolve(j, pv)
            m = score(j)
            print(f"{j.get('xid') or '-'} | {j.get('t')} | {j.get('cn')} | {j.get('loc')}")
            print(f"  status {st['st']} ({'; '.join(st['ev'])}) | trust {pv['trust']}" + (f" | errors {pv['errors']}" if pv['errors'] else ""))
            print(f"  overall {m['overall']} [{m['band']}] tech {m['tech']} exp {m['exp']} ind {m['ind']} loc {m['loc']} sal {m['sal']} emp {m['emp']}")
            if m["x"]:
                print(f"  EXCLUDED: {', '.join(m['x'])}")
        return 0

    data = _load(o.db)
    jobs = data.setdefault("jobs", [])
    if o.cmd == "ingest":
        with open(o.file, encoding="utf-8") as f:
            payload = f.read()
        meta = {"method": o.method, "origin": o.origin, "received_at": o.received_at}
        _, rep = ingest(payload, jobs, o.source, meta, keep_desc=o.keep_desc)
        print(f"in {rep['in']} | added {len(rep['added'])} | updated {len(rep['updated'])} | seen {rep['seen']} | "
              f"quarantined {len(rep['quarantined'])} | errors {len(rep['errors'])}")
        for x in rep["added"] + rep["updated"]:
            print(f"  {x['st']:<11} {x['o']:>3} {x['b']:<8} {x['t']} — {x['cn']}")
        for q in rep["quarantined"]:
            print(f"  QUARANTINE {q.get('xid') or '-'}: {'; '.join(q['why'])}")
        for e in rep["errors"]:
            print(f"  ERROR {e}")
    elif o.cmd == "refresh":
        ch = refresh(jobs)
        print(f"status changes {len(ch)}")
        for k, a, b in ch[:20]:
            print(f"  {k}: {a} -> {b}")
    elif o.cmd == "verify":
        ch = verify(jobs, o.key, o.state, o.via, o.at)
        print("not found" if ch is None else f"recorded; changes {ch}")
    elif o.cmd == "list":
        rows = [j for j in jobs if "st" in j and (not o.st or j["st"] == o.st) and (not o.band or (j.get("m") or {}).get("b") == o.band)]
        rows.sort(key=lambda j: -(j.get("m") or {}).get("o", 0))
        for j in rows[:o.n]:
            print(f"{j['st']:<11} {(j.get('m') or {}).get('o', 0):>3} {j.get('t')} — {j.get('cn')} ({j.get('loc')})")
        return 0
    if not getattr(o, "dry_run", False):
        _save(o.db, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
