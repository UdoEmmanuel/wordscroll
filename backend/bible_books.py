"""
Canonical Bible book registry: names, common abbreviations, and chapter
counts (standard across public-domain translations like KJV/ASV/WEB — this
is structural metadata, not copyrighted text, so it's safe to hardcode).

Chapter counts are used to reject implausible detections (e.g. "John
chapter 50" — John only has 21).

Each of the 66 books is listed explicitly (rather than derived from a
"numbered book" abstraction) so that ambiguous cases — e.g. plain "John"
(the Gospel) vs. "1/2/3 John" (the epistles) — are unambiguous by
construction instead of needing special-cased disambiguation logic.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Book:
    canonical: str
    aliases: tuple[str, ...]  # all lowercase, including the canonical name itself
    max_chapter: int
    # One canonical 2-3 letter code per book, unique across all 66 — the
    # "short reference" form (see /reference/short-codes and the app's Help
    # menu). Not a mechanical first-N-letters slice: several book names
    # collide too hard for that (Job/Joshua/Joel/Jonah/John all start "Jo";
    # Judges/Jude both reduce to "Jud" even at 3 letters), so this follows
    # first-2-letters, escalating to first-3 (or, for the handful of clashes
    # that still aren't unique at 3, a standard biblical abbreviation
    # instead) only where needed to stay unique — e.g. Philippians/Philemon
    # both start "Phi", so they're "php"/"phm" rather than a raw prefix.
    # Verified unique across all 66 (see the module-level assertion below).
    short_code: str


def _numbered_aliases(n: int, *bases: str) -> tuple[str, ...]:
    """Generate alias variants for a numbered book, e.g. n=1, base="samuel" ->
    "1 samuel", "1st samuel", "first samuel", "i samuel", "1 sam", ..."""
    ordinal_word = {1: "first", 2: "second", 3: "third"}[n]
    ordinal_suffix = {1: "1st", 2: "2nd", 3: "3rd"}[n]
    roman = {1: "i", 2: "ii", 3: "iii"}[n]
    prefixes = (str(n), ordinal_word, ordinal_suffix, roman)
    out = []
    for base in bases:
        for prefix in prefixes:
            out.append(f"{prefix} {base}")
    return tuple(out)


BOOKS: list[Book] = [
    Book("Genesis", ("genesis", "gen", "gn", "ge"), 50, "gen"),
    Book("Exodus", ("exodus", "exod", "exo", "ex"), 40, "exo"),
    Book("Leviticus", ("leviticus", "lev", "lv"), 27, "lev"),
    Book("Numbers", ("numbers", "num", "nm", "nu"), 36, "num"),
    Book("Deuteronomy", ("deuteronomy", "deut", "dt"), 34, "deu"),
    Book("Joshua", ("joshua", "josh", "jos"), 24, "jos"),
    Book("Judges", ("judges", "judg", "jdg"), 21, "jdg"),
    Book("Ruth", ("ruth", "rth", "ru"), 4, "rut"),
    Book("1 Samuel", _numbered_aliases(1, "samuel", "sam", "sm"), 31, "1sa"),
    Book("2 Samuel", _numbered_aliases(2, "samuel", "sam", "sm"), 24, "2sa"),
    Book("1 Kings", _numbered_aliases(1, "kings", "kgs", "kg"), 22, "1ki"),
    Book("2 Kings", _numbered_aliases(2, "kings", "kgs", "kg"), 25, "2ki"),
    Book("1 Chronicles", _numbered_aliases(1, "chronicles", "chron", "chr"), 29, "1ch"),
    Book("2 Chronicles", _numbered_aliases(2, "chronicles", "chron", "chr"), 36, "2ch"),
    Book("Ezra", ("ezra", "ezr"), 10, "ezr"),
    Book("Nehemiah", ("nehemiah", "neh"), 13, "neh"),
    Book("Esther", ("esther", "esth", "est", "es"), 10, "est"),
    Book("Job", ("job", "jb"), 42, "job"),
    Book("Psalms", ("psalms", "psalm", "ps", "psa", "pslm"), 150, "psa"),
    Book("Proverbs", ("proverbs", "prov", "prv", "pr"), 31, "pro"),
    Book("Ecclesiastes", ("ecclesiastes", "eccl", "eccles", "ecc"), 12, "ecc"),
    Book("Song of Solomon", ("song of solomon", "song of songs", "canticles", "sos", "sng", "song"), 8, "sos"),
    Book("Isaiah", ("isaiah", "isa", "is"), 66, "isa"),
    Book("Jeremiah", ("jeremiah", "jer", "je"), 52, "jer"),
    Book("Lamentations", ("lamentations", "lam"), 5, "lam"),
    Book("Ezekiel", ("ezekiel", "ezek", "eze"), 48, "eze"),
    Book("Daniel", ("daniel", "dan", "dn", "da"), 12, "dan"),
    Book("Hosea", ("hosea", "hos", "ho"), 14, "hos"),
    Book("Joel", ("joel", "jl"), 3, "joe"),
    Book("Amos", ("amos", "am"), 9, "amo"),
    Book("Obadiah", ("obadiah", "obad", "ob"), 1, "oba"),
    Book("Jonah", ("jonah", "jnh", "jon"), 4, "jon"),
    Book("Micah", ("micah", "mic"), 7, "mic"),
    Book("Nahum", ("nahum", "nah"), 3, "nah"),
    Book("Habakkuk", ("habakkuk", "hab"), 3, "hab"),
    Book("Zephaniah", ("zephaniah", "zeph"), 3, "zep"),
    Book("Haggai", ("haggai", "hag"), 2, "hag"),
    Book("Zechariah", ("zechariah", "zech"), 14, "zec"),
    Book("Malachi", ("malachi", "mal"), 4, "mal"),
    Book("Matthew", ("matthew", "matt", "mt"), 28, "mat"),
    Book("Mark", ("mark", "mrk", "mk"), 16, "mar"),
    Book("Luke", ("luke", "luk", "lk"), 24, "luk"),
    Book("John", ("john", "jn", "jhn"), 21, "joh"),
    Book("Acts", ("acts", "act", "ac"), 28, "act"),
    Book("Romans", ("romans", "rom", "rm", "ro"), 16, "rom"),
    Book("1 Corinthians", _numbered_aliases(1, "corinthians", "cor"), 16, "1co"),
    Book("2 Corinthians", _numbered_aliases(2, "corinthians", "cor"), 13, "2co"),
    Book("Galatians", ("galatians", "gal", "ga"), 6, "gal"),
    Book("Ephesians", ("ephesians", "eph", "ep"), 6, "eph"),
    Book("Philippians", ("philippians", "php"), 4, "php"),
    Book("Colossians", ("colossians", "col"), 4, "col"),
    Book("1 Thessalonians", _numbered_aliases(1, "thessalonians", "thess", "th", "the"), 5, "1th"),
    Book("2 Thessalonians", _numbered_aliases(2, "thessalonians", "thess", "th", "the"), 3, "2th"),
    Book("1 Timothy", _numbered_aliases(1, "timothy", "tim", "ti"), 6, "1ti"),
    Book("2 Timothy", _numbered_aliases(2, "timothy", "tim", "ti"), 4, "2ti"),
    Book("Titus", ("titus", "tit"), 3, "tit"),
    Book("Philemon", ("philemon", "phlm", "phm", "phil"), 1, "phm"),
    Book("Hebrews", ("hebrews", "heb", "he"), 13, "heb"),
    Book("James", ("james", "jas", "jm", "ja"), 5, "jam"),
    Book("1 Peter", _numbered_aliases(1, "peter", "pet", "pt", "pe"), 5, "1pe"),
    Book("2 Peter", _numbered_aliases(2, "peter", "pet", "pt", "pe"), 3, "2pe"),
    Book("1 John", _numbered_aliases(1, "john", "jn", "jhn"), 5, "1jo"),
    Book("2 John", _numbered_aliases(2, "john", "jn", "jhn"), 1, "2jo"),
    Book("3 John", _numbered_aliases(3, "john", "jn", "jhn"), 1, "3jo"),
    Book("Jude", ("jude", "jud"), 1, "jud"),
    Book("Revelation", ("revelation", "rev", "revelations", "re"), 22, "rev"),
]


def _build_registry() -> dict[str, tuple[str, int]]:
    registry: dict[str, tuple[str, int]] = {}
    for book in BOOKS:
        for alias in (*book.aliases, book.short_code):
            registry[alias] = (book.canonical, book.max_chapter)
    return registry


# lowercase alias -> (canonical name, max chapter count)
BOOK_REGISTRY: dict[str, tuple[str, int]] = _build_registry()

# Every short code must be unique across all 66 books — a collision here
# would mean two books silently overwrite each other's entry in
# BOOK_REGISTRY, breaking reference detection for whichever lost. Checked at
# import time rather than only in a test, since this table is meant to stay
# hand-edited (see the Book.short_code docstring above).
_short_code_owners: dict[str, str] = {}
for _book in BOOKS:
    _prior = _short_code_owners.get(_book.short_code)
    if _prior is not None:
        raise AssertionError(f"Duplicate short_code {_book.short_code!r}: {_prior} and {_book.canonical}")
    _short_code_owners[_book.short_code] = _book.canonical
del _short_code_owners, _prior, _book
