"""
Path resolution that works both in dev (running main.py straight from
source) and frozen (PyInstaller-built .exe) — see backend/PACKAGING.md.

Two distinct kinds of path, resolved differently on purpose:

- resource_dir(): READ-ONLY bundled files shipped with the app (bible_data/,
  overlay/). PyInstaller's --onefile mode extracts these into a temporary
  directory (sys._MEIPASS) that exists for the life of the running process —
  fine to read from, but it's recreated fresh (and the old one deleted) on
  every launch.
- writable_dir(): PERSISTED user data (favorites, history, queue, theme,
  uploaded background images) that must survive between runs. Using
  resource_dir()'s logic here would silently discard the operator's saved
  favorites/theme every single time the app restarts, since sys._MEIPASS is
  wiped on exit — this has to live next to the .exe instead, in a real
  directory PyInstaller never touches.
"""
import sys
from pathlib import Path

# PyInstaller sets sys.frozen = True and sys._MEIPASS to the extraction dir
# on a frozen build; both are absent when running from source.
_FROZEN = getattr(sys, "frozen", False)


def resource_dir(*parts: str) -> Path:
    base = Path(sys._MEIPASS) if _FROZEN else Path(__file__).parent  # noqa: SLF001
    return base.joinpath(*parts)


def writable_dir(*parts: str) -> Path:
    base = Path(sys.executable).parent if _FROZEN else Path(__file__).parent
    return base.joinpath(*parts)
