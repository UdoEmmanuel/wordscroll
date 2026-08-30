"""
Milestone 2/6: explicit scripture reference detection (FR-3.1 - FR-3.3) plus
lightweight voice navigation commands (next/previous/jump-to-verse).

Parses a transcript string for spoken/written scripture references —
"turn to John chapter 3 verse 16", "First Corinthians 13:4-7", "Romans 8" —
and normalizes them into a structured book/chapter/verse model, each tagged
with a confidence level.

Known limitation (per PRD Section 10 "Risks & Open Questions"): a handful of
book names double as common English words (Job, Acts, Mark, Titus, Numbers,
Judges, Joel, Amos). A casual "there are numbers 3 and 4 on the list" will
false-trigger as "Numbers 3:4". To manage that risk without just rejecting
those matches outright, every detection carries a `confidence`:
"low" only when an ambiguous book name is matched with no explicit
"chapter"/"verse"/":" marker (i.e. it's relying purely on bare adjacent
numbers) — every other case, including bare numbers on an unambiguous book
like "John 10 10", is "high". The display engine auto-pushes "high"
confidence hits and leaves "low" ones sitting in the detected-references
list for the operator to confirm. This is a heuristic stand-in for the
fuller confidence-scoring system in FR-5.1/5.2 — real-world false-positive
rates still need calibration against actual sermon audio.
"""
import re
from dataclasses import dataclass
from typing import Optional

from bible_books import BOOK_REGISTRY
from number_words import normalize_numbers

# Book names that double as common English words — see module docstring.
AMBIGUOUS_BOOKS = {"Job", "Acts", "Mark", "Titus", "Numbers", "Judges", "Joel", "Amos"}


@dataclass
class DetectedReference:
    book: str
    chapter: int
    verse_start: int | None
    verse_end: int | None
    raw_text: str
    confidence: str = "high"  # "high" or "low"


def _build_book_pattern() -> re.Pattern:
    # Longest alias first so e.g. "1 corinthians" is preferred over the "1 cor"
    # abbreviation when both would match at the same position.
    aliases = sorted(BOOK_REGISTRY.keys(), key=len, reverse=True)
    escaped = [re.escape(a) for a in aliases]
    return re.compile(r"\b(" + "|".join(escaped) + r")\b")


_BOOK_PATTERN = _build_book_pattern()

_CHAPTER_KEYWORD = r"(chapter|chap|ch\.?)"
# Optional: people very often cite verses with no separator word at all —
# "John ten ten" for John 10:10 — so a bare number directly after the
# chapter number counts too, not just "verse 16" / "v16" / ":16".
_VERSE_SEP = r"(:|verses|verse|vv?\.?)"
_RANGE_SEP = r"(?:-|–|—|to|through|thru)"
# Whisper often punctuates spoken numbers as separate sentences — "John 10.
# 10." — so the gap between chapter and verse numbers needs to tolerate a
# trailing period/comma glued onto the first number, not just whitespace.
_GAP = r"[\s,.]*"

# Groups: 1=chapter keyword, 2=chapter number, 3=verse-sep keyword,
# 4=verse number, 5=verse-range end number. Groups 1 and 3 are only used to
# judge confidence — their presence means the speaker used an explicit
# marker ("chapter"/"verse"/":") rather than just adjacent bare numbers.
_REST_PATTERN = re.compile(
    rf"^{_GAP}(?:{_CHAPTER_KEYWORD})?{_GAP}(\d{{1,3}})"
    rf"(?:{_GAP}(?:{_VERSE_SEP})?{_GAP}(\d{{1,3}})"
    rf"(?:{_GAP}{_RANGE_SEP}{_GAP}(\d{{1,3}}))?"
    rf")?",
    re.IGNORECASE,
)


# Typed search input is messier than a speech transcript: stray punctuation
# ("re;5,12") and abbreviations glued straight to numbers with no space at
# all ("re5 12", "php4") are both common when someone's typing fast. Both get
# normalized away before matching rather than needing special-case regexes.
_JUNK_CHAR_RE = re.compile(r"[^a-zA-Z0-9\s:.,\-–—]")
_LETTER_DIGIT_BOUNDARY_RE = re.compile(r"(?<=[a-zA-Z])(?=\d)")


def _clean_query(text: str) -> str:
    text = _JUNK_CHAR_RE.sub(" ", text)
    return _LETTER_DIGIT_BOUNDARY_RE.sub(" ", text)


def _book_mentioned(text: str) -> bool:
    """True if any recognized book name appears anywhere in `text`."""
    return _BOOK_PATTERN.search(normalize_numbers(text).lower()) is not None


def detect_bare_book(text: str) -> Optional[str]:
    """If `text` is *just* a recognized book name/alias/short-code with no
    chapter or verse at all (e.g. typing "php" and stopping there), returns
    its canonical name — else None.

    Deliberately separate from detect_references(), which is shared with
    live speech detection and *correctly* ignores a bare book mention with
    no chapter (a sermon saying "in Philippians we read..." shouldn't
    auto-navigate). Manual typed search is a different context — someone
    who typed only a short code clearly wants that book, so main.py's
    /search/reference falls back to this and defaults to chapter 1 rather
    than showing nothing."""
    normalized = normalize_numbers(_clean_query(text)).strip().lower()
    return BOOK_REGISTRY[normalized][0] if normalized in BOOK_REGISTRY else None


def detect_references(text: str) -> list[DetectedReference]:
    """Find every plausible explicit scripture reference in `text`."""
    normalized = normalize_numbers(_clean_query(text)).lower()
    results: list[DetectedReference] = []

    for m in _BOOK_PATTERN.finditer(normalized):
        alias = m.group(1)
        canonical, max_chapter = BOOK_REGISTRY[alias]

        rest = normalized[m.end():]
        rm = _REST_PATTERN.match(rest)
        if not rm or rm.group(2) is None:
            continue  # book name wasn't followed by a chapter number — skip

        chapter_keyword = rm.group(1)
        chapter = int(rm.group(2))
        if not (1 <= chapter <= max_chapter):
            continue

        verse_sep = rm.group(3)
        verse_start = int(rm.group(4)) if rm.group(4) else None
        verse_end = int(rm.group(5)) if rm.group(5) else None
        if verse_start is not None and not (1 <= verse_start <= 176):
            # 176 = longest chapter (Psalm 119); anything past that is implausible
            # as a verse number — demote to a chapter-only reference rather
            # than dropping it, since the book+chapter part is still good.
            verse_start = None
            verse_end = None
        if verse_end is not None and (verse_end < (verse_start or 0) or verse_end > 176):
            verse_end = None  # nonsensical range — keep the single verse, drop the range

        had_explicit_marker = bool(chapter_keyword) or bool(verse_sep)
        confidence = "low" if (canonical in AMBIGUOUS_BOOKS and not had_explicit_marker) else "high"

        raw_text = normalized[m.start():m.end() + rm.end()].strip()
        results.append(
            DetectedReference(
                book=canonical,
                chapter=chapter,
                verse_start=verse_start,
                verse_end=verse_end,
                raw_text=raw_text,
                confidence=confidence,
            )
        )

    return results


# Deliberately anchored on "verse" / "back" rather than single generic words
# like "next" or "continue" alone — those show up constantly in ordinary
# sermon speech and would false-trigger navigation on every other sentence.
_NEXT_VERSE_RE = re.compile(r"\bnext\s+verse\b", re.IGNORECASE)
_PREVIOUS_VERSE_RE = re.compile(
    r"\b(?:previous\s+verse|go\s+back(?:\s+(?:a|one)\s+verse)?|back\s+(?:a|one)\s+verse|back\s+up)\b",
    re.IGNORECASE,
)
_BARE_VERSE_RE = re.compile(r"\bverses?\s+(\d{1,3})\b", re.IGNORECASE)


def detect_next_verse_command(text: str) -> bool:
    """True if the operator/preacher said "next verse" (or a close variant
    like "go to the next verse" / "move to the next verse" — "next verse"
    still appears adjacently in those). Advances the display by one verse."""
    return bool(_NEXT_VERSE_RE.search(text))


def detect_previous_verse_command(text: str) -> bool:
    """True for "previous verse", "go back", "back up", etc. "go back" alone
    carries more false-trigger risk than the others (it's a common phrase
    outside of scripture navigation too) but was requested explicitly."""
    return bool(_PREVIOUS_VERSE_RE.search(text))


def detect_bare_verse_jump(text: str) -> int | None:
    """Matches a bare "verse N" with no book name anywhere in the same text —
    e.g. mid-reading, the preacher says "verse 17" without repeating "John
    chapter 3". Returns the verse number, or None if no such bare mention
    exists (or if a book name is also present, in which case detect_references
    already owns that text and this shouldn't double-handle it)."""
    if _book_mentioned(text):
        return None
    m = _BARE_VERSE_RE.search(normalize_numbers(text).lower())
    return int(m.group(1)) if m else None
