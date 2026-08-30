"""
Quick standalone sanity checks for the milestone 2 reference detector.
Run with: venv\\Scripts\\python.exe test_reference_parser.py
Not wired into a test framework yet — just fast manual verification.
"""
from reference_parser import (
    detect_bare_verse_jump,
    detect_next_verse_command,
    detect_previous_verse_command,
    detect_references,
)


CASES = [
    ("turn to John chapter 3 verse 16", [("John", 3, 16, None)]),
    ("For God so loved the world, John 3:16 says", [("John", 3, 16, None)]),
    ("open your bibles to First Corinthians 13:4-7", [("1 Corinthians", 13, 4, 7)]),
    ("open your bibles to 1 Corinthians thirteen verse four through seven", [("1 Corinthians", 13, 4, 7)]),
    ("open your bibles to 1 Corinthians thirteen four through seven", [("1 Corinthians", 13, 4, 7)]),  # no separator word, but bare adjacent numbers now count too
    ("John 10 10", [("John", 10, 10, None)]),  # bare "book chapter verse", no keywords at all
    ("John 10. 10.", [("John", 10, 10, None)]),  # whisper often punctuates spoken numbers as separate sentences
    ("Genesis 1. The earth was without form. 10 men came", [("Genesis", 1, None, None)]),  # unrelated later digit doesn't get grabbed as a verse
    ("John chapter 3 the crowd grew", [("John", 3, None, None)]),  # non-numeric words after chapter number — stays chapter-only, doesn't grab a stray digit
    ("let's read Romans chapter eight", [("Romans", 8, None, None)]),
    ("second timothy chapter 3 verses 16 to 17", [("2 Timothy", 3, 16, 17)]),
    ("turn to 1 John chapter 4 verse 8", [("1 John", 4, 8, None)]),
    ("just plain john walked in", []),  # "John" alone with no chapter number -> no match
    ("Genesis 1:1", [("Genesis", 1, 1, None)]),
    ("Song of Solomon chapter 2 verse 1", [("Song of Solomon", 2, 1, None)]),
    ("John chapter 50 verse 1", []),  # John only has 21 chapters -> rejected
    ("Psalm 119:105", [("Psalms", 119, 105, None)]),
    ("2nd Corinthians chapter 5 verse 3", [("2 Corinthians", 5, 3, None)]),
    ("1st John chapter 1 verse 9", [("1 John", 1, 9, None)]),
    ("re 5 12", [("Revelation", 5, 12, None)]),
    ("rev 5 12", [("Revelation", 5, 12, None)]),
    ("re5 12", [("Revelation", 5, 12, None)]),  # abbreviation glued straight to the chapter number
    ("php 4 13", [("Philippians", 4, 13, None)]),
    ("phil 1 5", [("Philemon", 1, 5, None)]),  # "phil" -> Philemon, "php" -> Philippians (per product decision)
    ("re;5,12", [("Revelation", 5, 12, None)]),  # stray punctuation disregarded
]


CONFIDENCE_CASES = [
    ("there are numbers 3 4 on the list", "low"),  # ambiguous book, bare numbers -> low
    ("read Numbers chapter 3 verse 4", "high"),  # ambiguous book, but explicit markers -> high
    ("Numbers 3:4", "high"),  # ambiguous book, but colon is explicit -> high
    ("John 10 10", "high"),  # unambiguous book, bare numbers still fine -> high
]

NAV_CASES = [
    ("next verse", detect_next_verse_command, True),
    ("let's go to the next verse", detect_next_verse_command, True),
    ("move to the next verse please", detect_next_verse_command, True),
    ("the next thing I want to say", detect_next_verse_command, False),
    ("previous verse", detect_previous_verse_command, True),
    ("go back", detect_previous_verse_command, True),
    ("go back a verse", detect_previous_verse_command, True),
    ("back up", detect_previous_verse_command, True),
    ("next verse", detect_previous_verse_command, False),
]

BARE_JUMP_CASES = [
    ("verse 17", 17),
    ("now look at verse 5", 5),
    ("John 3 verse 17", None),  # book present -> not a bare jump, detect_references owns this
    ("no verse number here", None),
]


def run():
    passed = 0
    failed = 0
    for text, expected in CASES:
        refs = detect_references(text)
        actual = [(r.book, r.chapter, r.verse_start, r.verse_end) for r in refs]
        ok = actual == expected
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {text!r}\n    expected={expected}\n    actual  ={actual}")

    for text, expected_confidence in CONFIDENCE_CASES:
        refs = detect_references(text)
        actual = refs[0].confidence if refs else None
        ok = actual == expected_confidence
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] confidence({text!r}) expected={expected_confidence} actual={actual}")

    for text, fn, expected in NAV_CASES:
        actual = fn(text)
        ok = actual == expected
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {fn.__name__}({text!r}) expected={expected} actual={actual}")

    for text, expected in BARE_JUMP_CASES:
        actual = detect_bare_verse_jump(text)
        ok = actual == expected
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] detect_bare_verse_jump({text!r}) expected={expected} actual={actual}")

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
