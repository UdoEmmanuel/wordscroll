"""
Disk-persisted (backend/data/favorites.json) quick-access list of verses the
operator has marked as favorites. Unlike history, this is meant to survive
restarts — it's built up once and reused across many services.
"""
import uuid
from typing import Optional

import json_store

_FILENAME = "favorites.json"
_favorites: list[dict] = json_store.load(_FILENAME, [])


def _dedupe_key(book: str, chapter: int, verse_start: Optional[int], verse_end: Optional[int], translation: str) -> tuple:
    return (book, chapter, verse_start, verse_end, translation)


def add(book: str, chapter: int, verse_start: Optional[int], verse_end: Optional[int], translation: str, text: str, reference: str) -> dict:
    key = _dedupe_key(book, chapter, verse_start, verse_end, translation)
    for fav in _favorites:
        if _dedupe_key(fav["book"], fav["chapter"], fav["verseStart"], fav["verseEnd"], fav["translation"]) == key:
            return fav

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
    _favorites.append(entry)
    json_store.save(_FILENAME, _favorites)
    return entry


def remove(fav_id: str) -> bool:
    for i, fav in enumerate(_favorites):
        if fav["id"] == fav_id:
            del _favorites[i]
            json_store.save(_FILENAME, _favorites)
            return True
    return False


def list_all() -> list[dict]:
    return list(_favorites)
