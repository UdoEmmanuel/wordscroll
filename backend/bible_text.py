"""
Milestone 3: verse text lookup against the bundled KJV translation.

Data source: bible_data/kjv/*.json (public-domain KJV text, MIT-licensed
JSON packaging by aruljohn/Bible-kjv — see bible_data/kjv/LICENSE-source.txt).
Loaded once and cached in memory; the whole KJV is ~5MB, trivial to hold.
"""
import json
import re

from app_paths import resource_dir
from bible_books import BOOKS

_DATA_DIR = resource_dir("bible_data", "kjv")

_cache: dict[str, dict] = {}


def _filename_for(book: str) -> str:
    return book.replace(" ", "") + ".json"


def _load_book(book: str) -> dict:
    if book not in _cache:
        path = _DATA_DIR / _filename_for(book)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Index by chapter number (str) -> {verse number (str) -> text}
        chapters = {}
        for ch in data["chapters"]:
            chapters[ch["chapter"]] = {v["verse"]: v["text"] for v in ch["verses"]}
        _cache[book] = chapters
    return _cache[book]


def get_verse_text(book: str, chapter: int, verse_start: int | None, verse_end: int | None) -> str | None:
    """Returns the verse text for a reference, or None if not found.
    - Chapter-only reference (verse_start is None): returns the whole chapter, one verse per line.
    - Single verse: returns just that verse's text.
    - Verse range: returns the range joined with spaces, verse numbers included inline.
    """
    try:
        chapters = _load_book(book)
    except FileNotFoundError:
        return None

    verses = chapters.get(str(chapter))
    if verses is None:
        return None

    if verse_start is None:
        return "\n".join(f"{num} {text}" for num, text in verses.items())

    end = verse_end or verse_start
    parts = []
    for v in range(verse_start, end + 1):
        text = verses.get(str(v))
        if text is None:
            continue
        parts.append(f"{text}" if end == verse_start else f"[{v}] {text}")
    if not parts:
        return None
    return " ".join(parts)


def get_chapter_verses(book: str, chapter: int) -> list[dict] | None:
    """Every verse in a chapter as [{verse, text}, ...] in order, or None if
    the book/chapter doesn't exist. Powers the chapter navigator — jump to
    any verse in the currently displayed chapter without retyping a search."""
    try:
        chapters = _load_book(book)
    except FileNotFoundError:
        return None
    verses = chapters.get(str(chapter))
    if verses is None:
        return None
    return [{"verse": int(num), "text": text} for num, text in verses.items()]


def get_last_verse_number(book: str, chapter: int) -> int | None:
    """Returns the highest verse number in `chapter`, or None if the book/chapter
    doesn't exist. Used to roll "previous verse" back into the prior chapter."""
    try:
        chapters = _load_book(book)
    except FileNotFoundError:
        return None
    verses = chapters.get(str(chapter))
    if not verses:
        return None
    return max(int(v) for v in verses.keys())


def preload_all() -> None:
    """Loads every book into cache up front — needed for keyword search to
    scan the whole Bible instead of only whatever's been looked up so far.
    Cheap: ~5MB total across all 66 books."""
    for book in BOOKS:
        _load_book(book.canonical)


_all_verses_cache: list[dict] | None = None


def get_all_verses() -> list[dict]:
    """Every verse in canonical book order as a flat list — used by recitation
    fuzzy matching, which needs to scan the whole translation per call."""
    global _all_verses_cache
    if _all_verses_cache is None:
        preload_all()
        verses = []
        for book in BOOKS:
            chapters = _load_book(book.canonical)
            for chapter_num, vs in chapters.items():
                for verse_num, text in vs.items():
                    verses.append(
                        {
                            "book": book.canonical,
                            "chapter": int(chapter_num),
                            "verse": int(verse_num),
                            "text": text,
                        }
                    )
        _all_verses_cache = verses
    return _all_verses_cache


def search_keyword(query: str, limit: int = 50) -> list[dict]:
    """Multi-word search across the whole bundled translation: each query
    word is matched independently (whole-word, case-insensitive) rather than
    requiring the exact phrase in that exact order — "shepherd lord" finds
    "The LORD is my shepherd" even though the words appear reversed. Results
    are ranked by how many distinct query words a verse contains (most
    matches first), then by canonical book order as a tiebreak."""
    words = re.findall(r"[a-zA-Z']+", query.lower())
    if not words:
        return []
    patterns = [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in words]

    scored: list[tuple[int, dict]] = []
    for verse in get_all_verses():
        score = sum(1 for p in patterns if p.search(verse["text"]))
        if score > 0:
            scored.append((score, verse))

    # Stable sort: get_all_verses() is already in canonical book order, so
    # equal-score results keep that order rather than an arbitrary one.
    scored.sort(key=lambda pair: -pair[0])
    return [v for _score, v in scored[:limit]]
