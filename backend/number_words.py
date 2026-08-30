"""
Spoken-number-word -> digit conversion, e.g. "chapter one nineteen" or
"chapter one hundred and nineteen" -> "chapter 119". Whisper often already
renders spoken numbers as digits, but not always — this normalizes whatever
comes through so the reference parser only has to handle digits.

Covers 0-999, which comfortably covers every chapter/verse number in the
Bible (max chapter: Psalms 150; max verse: Psalm 119:176).
"""
import re

_DIGITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_ONES = {**_DIGITS, **_TEENS}  # kept for callers that just need "is this a number word"

# Ordinal-suffixed digits ("2nd", "3rd") must be tried before the bare
# letter/digit alternatives, or "2nd" splits into "2" + "nd" and breaks
# alias matching (e.g. "2nd corinthians" -> "2 nd corinthians").
_TOKEN_RE = re.compile(r"\d+(?:st|nd|rd|th)\b|[a-zA-Z']+|\d+|[^\sa-zA-Z\d]+")


def _consume_number(tokens: list[str], start: int) -> tuple[int, int] | None:
    """Try to parse a single number-word phrase starting at `start`, following
    normal English number grammar: an optional "X hundred (and)" prefix,
    followed by either a teen/ten (10-19), or a tens word optionally followed
    by a ones digit (e.g. "thirty four" = 34). Stops as soon as the number is
    grammatically complete — "thirteen four" is two numbers (13, 4), not one,
    since a teen can't be followed by another digit in standard English.
    Returns (value, tokens_consumed) or None if no number word is present."""
    i = start
    if i >= len(tokens):
        return None
    word = tokens[i].lower()

    hundred = 0
    if word in _DIGITS and i + 1 < len(tokens) and tokens[i + 1].lower() == "hundred":
        hundred = _DIGITS[word] * 100
        i += 2
        if i < len(tokens) and tokens[i].lower() == "and" and i + 1 < len(tokens) and tokens[i + 1].lower() in (_DIGITS.keys() | _TEENS.keys() | _TENS.keys()):
            i += 1  # "one hundred and nineteen" — skip the bridging "and"
        word = tokens[i].lower() if i < len(tokens) else ""
    elif word == "hundred":
        hundred = 100
        i += 1
        if i < len(tokens) and tokens[i].lower() == "and" and i + 1 < len(tokens) and tokens[i + 1].lower() in (_DIGITS.keys() | _TEENS.keys() | _TENS.keys()):
            i += 1
        word = tokens[i].lower() if i < len(tokens) else ""

    if word in _TENS:
        value = _TENS[word]
        i += 1
        if i < len(tokens) and tokens[i].lower() in _DIGITS:
            value += _DIGITS[tokens[i].lower()]
            i += 1
        return hundred + value, i - start

    if word in _TEENS:
        return hundred + _TEENS[word], i - start + 1

    if word in _DIGITS:
        return hundred + _DIGITS[word], i - start + 1

    if hundred:
        return hundred, i - start  # bare "X hundred" with nothing after it

    return None


def normalize_numbers(text: str) -> str:
    """Replace runs of spoken number words in `text` with digit strings,
    leaving already-numeric digits and non-number words untouched."""
    tokens = _TOKEN_RE.findall(text)
    out: list[str] = []
    i = 0
    while i < len(tokens):
        result = _consume_number(tokens, i)
        if result is not None:
            value, consumed = result
            out.append(str(value))
            i += consumed
        else:
            out.append(tokens[i])
            i += 1

    # Reassemble with single spaces; punctuation tokens attach without a
    # leading space so "16," / "16:" render naturally.
    rebuilt = ""
    for idx, tok in enumerate(out):
        if idx > 0 and not re.match(r"^[^\sa-zA-Z0-9]+$", tok):
            rebuilt += " "
        rebuilt += tok
    return rebuilt
