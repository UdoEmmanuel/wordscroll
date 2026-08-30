"""
Tiny stdlib-only JSON file persistence helper, used by favorites_store.py and
queue_store.py. Writes are atomic (write to a temp file, then os.replace) so a
crash mid-write can't corrupt the existing file.
"""
import json
import os
from typing import Any

from app_paths import writable_dir

DATA_DIR = writable_dir("data")


def load(filename: str, default: Any) -> Any:
    path = DATA_DIR / filename
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(filename: str, data: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / filename
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)
