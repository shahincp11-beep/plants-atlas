"""Adapter registry. Add a source: write adapters/<name>.py with NAME, detect(obj), parse(obj) -> canonical."""
from . import seek, jobposting

ADAPTERS = {seek.NAME: seek, jobposting.NAME: jobposting}


def get_adapter(name=None, obj=None):
    if name:
        if name not in ADAPTERS:
            raise ValueError(f"unknown source '{name}'; have {sorted(ADAPTERS)}")
        return ADAPTERS[name]
    for a in ADAPTERS.values():
        try:
            if a.detect(obj):
                return a
        except Exception:
            continue
    return None
