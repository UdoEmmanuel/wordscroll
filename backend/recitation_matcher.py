"""
Milestone 5: recitation/fuzzy matching (FR-4.1 - FR-4.3).

Matches spoken text against the full bundled translation to catch verses
quoted or paraphrased from memory — no "chapter/verse" citation needed, and
no requirement that the wording be exact (FR-4.2: "tolerate paraphrasing,
partial quotes, and minor misquotes"). Every match is treated as low
confidence (FR-4.3) regardless of score: recitation is inherently less
certain than an explicit citation, and per product decision these should
only ever show up as a suggestion for the operator to confirm, never
auto-push (see main.py's confidence gating).

Scorer choice: rapidfuzz offers several string-similarity algorithms.
token_set_ratio was tried first (it's the common recommendation for
"fuzzy match against a word bag") and rejected — it's length-insensitive in
a way that let a long, mostly-irrelevant verse (Zechariah 11:16) outscore
the actual intended match (Psalm 23:1) just for sharing a few words.
partial_ratio, which looks for the best-aligned substring match, correctly
matched 5/5 hand-tested paraphrases (Psalm 23:1, Philippians 4:13,
Proverbs 3:5, Romans 8:28, John 3:16) with scores 76-98, while ordinary
non-scripture sermon sentences scored 56-65 — a clean gap that
SCORE_THRESHOLD sits comfortably inside. Real sermon audio hasn't validated
this threshold yet; it may need recalibration (see PRD Section 10 risk).
"""
from rapidfuzz import fuzz, process

from bible_text import get_all_verses

MIN_WORDS = 5  # shorter snippets are too ambiguous to fuzzy-match reliably
MAX_WINDOW_WORDS = 25  # only match the tail of a long utterance
SCORE_THRESHOLD = 72

_choices_cache: list[str] | None = None


def _choices() -> list[str]:
    global _choices_cache
    if _choices_cache is None:
        _choices_cache = [v["text"] for v in get_all_verses()]
    return _choices_cache


def match_recitation(text: str) -> dict | None:
    """Returns {book, chapter, verse, text, score} for the best-matching
    verse, or None if nothing scores above SCORE_THRESHOLD."""
    words = text.split()
    if len(words) < MIN_WORDS:
        return None
    window = " ".join(words[-MAX_WINDOW_WORDS:])

    result = process.extractOne(window, _choices(), scorer=fuzz.partial_ratio)
    if result is None:
        return None
    _matched_text, score, idx = result
    if score < SCORE_THRESHOLD:
        return None

    verse = get_all_verses()[idx]
    return {
        "book": verse["book"],
        "chapter": verse["chapter"],
        "verse": verse["verse"],
        "text": verse["text"],
        "score": score,
    }
