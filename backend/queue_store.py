"""
Disk-persisted (backend/data/queue.json), order-sensitive list of verses the
operator has queued up ahead of time (e.g. a planned reading order before a
service starts). Persisted so prep work survives a crash/restart, unlike the
session-only history log.
"""
from typing import Optional
import uuid

import json_store

_FILENAME = "queue.json"
_queue: list[dict] = json_store.load(_FILENAME, [])


def add(book: str, chapter: int, verse_start: Optional[int], verse_end: Optional[int], translation: str, text: str, reference: str) -> dict:
    entry = {
        "id": uuid.uuid4().hex[:12],
        "book": book,
        "chapter": chapter,
        "verseStart": verse_start,
        "verseEnd": verse_end,
        "translation": translation,
        "text": text,
        "reference": reference,
    }
    _queue.append(entry)
    json_store.save(_FILENAME, _queue)
    return entry


def remove(item_id: str) -> bool:
    for i, item in enumerate(_queue):
        if item["id"] == item_id:
            del _queue[i]
            json_store.save(_FILENAME, _queue)
            return True
    return False


def move(item_id: str, direction: str) -> bool:
    for i, item in enumerate(_queue):
        if item["id"] == item_id:
            target = i - 1 if direction == "up" else i + 1
            if target < 0 or target >= len(_queue):
                return False
            _queue[i], _queue[target] = _queue[target], _queue[i]
            json_store.save(_FILENAME, _queue)
            return True
    return False


def pop_first() -> Optional[dict]:
    if not _queue:
        return None
    entry = _queue.pop(0)
    json_store.save(_FILENAME, _queue)
    return entry


def list_all() -> list[dict]:
    return list(_queue)
