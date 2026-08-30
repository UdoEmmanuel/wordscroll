"""
Disk-persisted (backend/data/theme_templates.json) named theme snapshots —
lets the operator save a complete look (every theme_store.py field) and
switch between several saved themes without re-tuning each control by hand.
"""
import time
import uuid
from typing import Optional

import json_store

_FILENAME = "theme_templates.json"

_templates: list[dict] = json_store.load(_FILENAME, [])


def list_all() -> list[dict]:
    return list(_templates)


def create(name: str, theme: dict) -> dict:
    template = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "theme": dict(theme),
        "createdAt": time.time(),
    }
    _templates.append(template)
    json_store.save(_FILENAME, _templates)
    return template


def get(template_id: str) -> Optional[dict]:
    return next((t for t in _templates if t["id"] == template_id), None)


def delete(template_id: str) -> bool:
    for i, t in enumerate(_templates):
        if t["id"] == template_id:
            del _templates[i]
            json_store.save(_FILENAME, _templates)
            return True
    return False
