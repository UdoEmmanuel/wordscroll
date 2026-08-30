"""
Session-only (in-memory, not persisted to disk) log of every verse actually
displayed, regardless of how it got on screen — voice auto-display, manual
search, chapter-nav click, next/previous, or a pending-suggestion approval.
Cleared on backend restart by design: "session history" per the PRD, not a
permanent record (see favorites_store.py for the persisted equivalent).
"""
import time
import uuid

MAX_HISTORY = 200

_history: list[dict] = []


def record(display_state: dict) -> dict:
    entry = {"id": uuid.uuid4().hex[:12], "addedAt": time.time(), **display_state}
    _history.append(entry)
    del _history[:-MAX_HISTORY]
    return entry


def list_all() -> list[dict]:
    return list(reversed(_history))


def clear() -> None:
    _history.clear()
