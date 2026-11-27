"""Plants Atlas job intelligence engine (stdlib only, zero cost).

    from tools.jobintel import ingest, refresh, verify
    jobs, report = ingest(seek_json, data["jobs"], source="seek", meta={"method": "user_supplied"})
"""
from .engine import ingest, refresh, verify, iter_records, to_record
from .adapters import get_adapter, ADAPTERS
from .match import score, load_profile
from .status import resolve, STATUSES
from .provenance import check

__all__ = ["ingest", "refresh", "verify", "iter_records", "to_record", "get_adapter", "ADAPTERS",
           "score", "load_profile", "resolve", "STATUSES", "check"]
