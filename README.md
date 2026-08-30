# AI Bible Transcriber

Real-time scripture detection & display for live church production. See
[`AI_Bible_Transcriber_PRD.docx`](AI_Bible_Transcriber_PRD.docx) for the full product spec.

## Build plan

The product is built in phases (per the PRD's own phasing), and Phase 1 itself
is broken into milestones so the pipeline can be proven incrementally:

1. ✅ **Audio → transcript** — device selection, rolling audio capture,
   local offline speech-to-text streamed live to the UI.
2. ✅ **Explicit reference detection** — parse "book chapter:verse" (including
   spoken numbers and abbreviations) from the live transcript.
3. ✅ **Display output** — verse lookup against a bundled KJV, NDI source +
   HTML overlay fallback, both driven by a shared display state.
4. ✅ **Manual reference/keyword search** — search the bundled KJV directly
   and push to output, bypassing detection entirely.
5. ✅ **Recitation/fuzzy matching** — verses recited or paraphrased from
   memory (no citation) are matched against the full bundled translation
   and surfaced at low confidence.
6. ✅ **Confidence scoring, auto-display, navigation commands, pending-suggestions
   panel** — pulled forward early (at user request) in a heuristic form.
   Full operator hotkey set (beyond next/previous verse) still open.

## Project layout

```
backend/
  bible_data/kjv/   Bundled public-domain KJV text (MIT-licensed JSON packaging
                     by aruljohn/Bible-kjv — see LICENSE-source.txt inside)
  overlay/           HTML overlay page for OBS Browser Source / vMix Web Browser input
  main.py            FastAPI app — capture, STT, detection, display state, NDI
app/                 Electron shell — operator UI
```

The two run as separate processes talking over `localhost` (REST + WebSocket
on port 8765). This mirrors the PRD's recommended stack and keeps the heavy
Python audio/ML dependencies out of the Electron process.

## Prerequisites

- **Node.js** (already installed on this machine)
- **Python 3.10+** — not currently installed on this machine. Install from
  [python.org](https://www.python.org/downloads/) (check "Add python.exe to PATH"
  during setup), then verify with:

  ```bash
  python --version
  ```

- A working microphone or audio input device for testing.

## Setup (production PC — one-time)

There's no compiled installer — see "Packaging" below for why. Instead,
`install.ps1` sets up a Python venv, installs both the backend and app
dependencies, and drops a **WordScroll** shortcut on the Desktop:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

(Or right-click `install.ps1` → "Run with PowerShell".) Needs Python 3.11+
and Node.js (LTS) already on PATH — the script checks for both and tells
you what's missing if not. Re-running it later (e.g. after a `git pull`) is
safe — it skips steps that are already done and just re-syncs dependencies.

From then on, launch the app from the **WordScroll** Desktop shortcut. The
first-ever launch of live transcription downloads the `faster-whisper`
model (default: `small`, ~500 MB) to a local cache — needs internet once,
then works fully offline per NFR-2.

## Setup (development)

**Backend:**

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**Frontend:**

```bash
cd app
npm install
```

## Running

```bash
cd app
npm start
```

That's it — `app/src/main.js` starts the Python backend itself (spawning
`backend\venv\Scripts\python.exe -m uvicorn ...`) as soon as Electron
launches, and stops it when the app quits. If it doesn't find a venv at
`backend/venv`, it logs a warning and the window still opens, but nothing
will work until the backend Setup step above has been done.

Everything main.js logs (its own messages and every `[backend] ...` line
from the spawned Python process) is also written to a timestamped file in
`logs/` — the Desktop shortcut points straight at `electron.exe` with no
console window at all (see "Packaging" below for why), so this is the only
place to look if something goes wrong without a visible terminal.
`Start WordScroll.ps1` is an optional alternative for watching that same
output live in a terminal instead.

If a backend is already running on port 8765 (e.g. you started one by hand
for debugging), Electron detects that and leaves it alone rather than
double-spawning — and won't kill it on quit either, since it isn't the one
that started it. To run the backend by hand instead (its own terminal, for
watching its logs directly):

```bash
cd backend
venv\Scripts\activate
uvicorn main:app --host 127.0.0.1 --port 8765
```

In the app window: pick your audio input device from the dropdown, click
**Start**, and speak. Finalized lines appear in the transcript log as they're
recognized; the italic line below shows the current in-progress utterance.
Click **Stop** to end capture.

### What "done" looks like for this milestone

- Devices populate in the dropdown (confirms the backend is reachable).
- Speaking into the selected device produces a live partial line within ~2s.
- Pausing after a sentence commits it as a finalized line in the log.
- Switching devices and restarting capture works without restarting the app.

## Milestone 2 — Explicit reference detection

Say a scripture reference while capturing (e.g. "turn to John chapter 3
verse 16", "First Corinthians thirteen four through seven") — a card
appears in the **Detected References** panel on the right. Known limitation
(flagged in the PRD itself, Section 10): a few book names double as common
English words (Job, Acts, Mark, Titus, Numbers, Judges, Joel, Amos), so a
casual "there are numbers 3 and 4 on the list" can false-trigger. That's
expected at this stage — confidence scoring / pending-review (milestone 6)
is what's meant to catch it.

Regression tests for the parser: `venv\Scripts\python.exe backend\test_reference_parser.py`

## Milestone 3 — Display output (NDI + HTML overlay)

Click any card in **Detected References** to push it live — it looks up the
verse text from the bundled KJV and updates:

- The **Now Displaying** panel in the app (with a **Clear** button — FR-5.3's
  "clear the display instantly" override).
- The **HTML overlay**, served at `http://127.0.0.1:8765/overlay/` — add this
  as an OBS Browser Source or a vMix Web Browser input (transparent background,
  updates live over WebSocket, no page reload needed).
- A live **NDI source** named "AI Bible Transcriber" — discoverable by vMix
  (native NDI support) or OBS (via the free [OBS NDI plugin](https://github.com/DistroAV/DistroAV)).
  Check `GET /status` for `ndi_available`/`ndi_error` if the source isn't
  showing up — the NDI runtime is bundled with the `ndi-python` package, so
  no separate SDK install should be needed, but this hasn't been tested
  against real production hardware yet (NFR-4).

Verse text comes from the bundled KJV (`backend/bible_data/kjv/`) — public
domain, no licensing restrictions per PRD Section 9. Licensed translations
(NIV, ESV, etc.) are Phase 2 scope.

The display styling (`backend/overlay/overlay.css` and
`backend/display_renderer.py`) is a placeholder — FR-8.1 calls for matching
the existing lyric-slide visual conventions, which we don't have yet. Both
files would need updating together once that style guide is available.

**Next/previous verse** (added beyond the original PRD scope, at user
request): once a verse is displayed —
- Say "next verse" (or "go to the next verse" / "move to the next verse" —
  the phrase "next verse" just needs to appear), or press **↓ / →**, to advance.
- Say "previous verse", "go back", or "back up", or press **↑ / ←**, to go back.

Voice and hotkey both call the same backend logic (`_advance_verse` /
`_retreat_verse` in `main.py`) and roll across chapter boundaries
automatically. No cross-book rollover yet (e.g. retreating past Genesis 1:1
is a no-op). "go back" alone carries more false-trigger risk than the other
phrases (it's common outside of scripture navigation too) — worth watching
during real-world use.

**Mid-reading verse jump**: if a verse is already displayed and the preacher
says just "verse 17" (no book/chapter repeated), the display jumps to that
verse of whatever's currently showing — `detect_bare_verse_jump` in
`reference_parser.py`. If a book *is* mentioned, normal reference detection
takes over instead, so this never double-handles a real citation.

## Milestone 4 — Manual reference/keyword search

Two independent search fields sit at the top of the app (not tied to a mode
toggle), and work regardless of whether audio capture is running, matching
FR-6.1/6.2's "operator can always push a verse manually":

- **Reference** (`F5` to jump to it): type a reference the same way you'd say
  it — "John 3:16", "Romans 8", "1 Cor 13:4-7". Press **Enter** to search,
  **Enter again** within ~0.7s to push the top result live hands-free.
- **Keyword** (`F6` to jump to it): type 3+ characters of a word or phrase
  (e.g. "shepherd") to search the full bundled KJV (~31,000 verses,
  case-insensitive substring match, capped at 50 results, book order).

Results appear live as you type (debounced ~250ms) in the left-hand results
column; click any result to push it, same as a detected reference card.

Typed queries are more forgiving than live speech: abbreviations glued
straight to numbers ("re5 12", "php4") and stray punctuation ("re;5,12")
both get normalized before matching (`_clean_query` in
`reference_parser.py`). Also fixed a real abbreviation collision: `php` now
means Philippians and `phil` means Philemon (previously both meant
Philippians) — matches the convention the user wanted; `re` was added as a
short alias for Revelation.

## Confidence scoring & auto-display (pulled forward from milestone 6)

Every detected reference now carries a `confidence` ("high" or "low"):

- **High confidence** auto-pushes straight to the display/overlay/NDI —
  no click needed. This covers ordinary explicit citations, and bare
  adjacent-number citations ("John ten ten") on any *unambiguous* book name.
- **Low confidence** — an *ambiguous* book name (Job, Acts, Mark, Titus,
  Numbers, Judges, Joel, Amos — see `AMBIGUOUS_BOOKS` in
  `reference_parser.py`) matched with **no** explicit "chapter"/"verse"/":"
  marker, e.g. "there are numbers 3 4 on the list" — only shows up in the
  Detected References panel (amber-bordered, "tap to confirm") and is never
  auto-pushed.

This is a heuristic stand-in for the PRD's full confidence-scoring system
(FR-5.1/5.2) — it's not a trained model, just a rule about explicit markers
vs. bare-number ambiguity. The pending-suggestions review *panel* UI (a
dedicated queue separate from the always-visible reference log) is still
open scope.

## Milestone 5 — Recitation/fuzzy matching

When a preacher quotes or paraphrases a verse from memory — no "chapter/verse"
citation at all — `recitation_matcher.py` fuzzy-matches the sentence against
all ~31,000 verses of the bundled KJV using `rapidfuzz`. Every match is
**always low confidence** regardless of score (never auto-pushed), per
product decision — recitation matching is inherently less certain than an
explicit citation, and only shows up in the Pending Suggestions panel for
the operator to approve or dismiss (FR-4.3, and the confidence system above).

Only runs as the last fallback in `main.py`'s per-segment handling — after
explicit citations, next/previous, and bare-verse-jump have all had a
chance, so it never fires on a sentence that's already been handled another
way. Scans the *entire* translation on every plain sentence anyone says (not
just ones that turn out to be scripture), so false-positive suggestions are
expected — that's exactly why these never auto-push.

**Scorer choice matters more than it looks**: `token_set_ratio` (the usual
first choice for word-bag fuzzy matching) was tried first and rejected — it
mismatched a Psalm 23:1 paraphrase to an unrelated, much longer Zechariah
verse that happened to share a few words, because it doesn't penalize length
mismatch. `partial_ratio` (best-aligned substring match) got 5/5 on
hand-tested paraphrases (Psalm 23:1, Philippians 4:13, Proverbs 3:5, Romans
8:28, John 3:16) with scores 76-98, while ordinary non-scripture sentences
scored 56-65 — `SCORE_THRESHOLD = 72` sits in that gap. Real sermon audio
hasn't validated this threshold yet (PRD Section 10's calibration risk
applies here too); ~0.4-0.5s per fuzzy-match call on this hardware.

**On "robustness to any phrasing"**: the request was for the system to
"flow with" however a preacher actually talks rather than requiring exact
wording. What's implemented is broader regex coverage (several next/previous
phrasings, the bare-verse-jump fallback) plus the confidence system so
ambiguous hits don't silently misfire — but this is still fundamentally
rule-based matching, not true natural-language understanding. Genuinely
open-ended phrasing tolerance is what milestone 5 (recitation/fuzzy matching)
is for; worth revisiting there.

## Milestone 6 additions — pending suggestions panel, chapter navigator, audio input resilience

**Pending Suggestions panel** (FR-5.2): low-confidence detections —
ambiguous-book bare-number citations and *every* recitation match — now go
to their own panel with **Approve** (pushes it live, same as clicking a
normal card) and **Dismiss** (just removes it) buttons, instead of sitting
mixed into the Detected References log. That log is now purely
informational — everything in it already auto-displayed. Every card (in
both panels) shows the **actual bundled scripture text** as its main
excerpt — not what was heard/recited — since that's what the operator
needs to judge a match; what was actually said stays as a smaller
"You said: ..." caption underneath for context (`previewText` vs `rawText`
in the `reference` WebSocket payload).

**Chapter-only references show verse 1, not the whole chapter**: saying
"Romans chapter eight" (or searching "Romans 8" with no verse) now displays
verse 1 of that chapter instead of dumping the entire chapter's text onto
the screen — `_apply_display` in `main.py` defaults a missing `verse_start`
to `1`. The Chapter Navigator (which reacts to any display push) comes up
automatically alongside it, so the rest of the chapter is one click away.

**Keyword search matches individual words, not a sequential phrase**:
"shepherd lord" now finds "The LORD is my shepherd" even though the words
appear in the opposite order — previously `search_keyword` required the
literal substring `"shepherd lord"` to appear verbatim. Each query word is
matched independently (whole-word, case-insensitive) and results are ranked
by how many distinct query words a verse contains, most matches first
(ties keep canonical book order). ~0.15-0.25s over all ~31k verses.

**Chapter Navigator**: whenever a verse is on screen — however it got there
(voice auto-display, search, next/previous, or another chapter-nav click) —
the left side of the Now Displaying panel lists every verse of that chapter,
highlights the current one, and pushes any verse you click straight to
display. No retyping a search to jump around a chapter. Fetches
`GET /chapter?book=&chapter=` and only re-fetches when the book/chapter
actually changes (not on every verse-only update within the same chapter).

**Audio input resilience** (for line-level/console sources — 3.5mm jack or
USB interface fed from a mixing console, not just a plain mic): the app
already lists every input device Windows exposes (`sounddevice`), so a
console feed should already appear in the dropdown once connected — nothing
new needed there. What *was* added: `audio_capture.py` now retries at a
device's own native sample rate (with software resampling to the 16kHz
Whisper needs) if forcing 16kHz outright fails to open, which is a common
real cause of "this device won't open" on pro-audio interfaces. **Caveat: I
could not test this against real digital-console hardware** — there's none
available in this environment — so this is reasoning-based resilience, not
a verified fix for your specific console. Two things worth knowing when you
wire it up:
- A mixing console's output is **line level**, meaningfully hotter than a
  microphone's signal. Feeding it into a **mic-level** input (a pink 3.5mm
  jack, or "boost"/gain enabled on that input) will likely clip/distort and
  hurt transcription accuracy far more than any software setting here could
  fix. Look for a dedicated **line-level input** — often a blue 3.5mm jack
  on a desktop's onboard sound card, or a proper input on a USB audio
  interface — and use the console's line/aux output, not its mic/XLR output,
  if it has both.
- If the exact device still won't open even after this fallback, the
  `/start` error message (surfaced as a red banner in the app) now comes
  from the *original* forced-16kHz failure, which is the more informative
  one to read/report.

**Device list cleanup + live refresh**: Windows exposes every physical
device once per audio host API (MME, DirectSound, WASAPI, WDM-KS), which
used to flood the dropdown with 3-4 duplicate entries per real device, plus
virtual/meta entries ("Microsoft Sound Mapper - Input") and WDM-KS-only
junk — unnamed "Microphone Array N ()" stubs, MIDI ports and speakers
misreported as inputs, and devices that fail to actually open (this
machine's Bluetooth headsets and Realtek mic jack both errored with
"Invalid device" when tested earlier). `list_input_devices()` now restricts
to WASAPI only — its own listing is already exactly one clean entry per
device Windows currently considers usable, which solved the duplication,
the junk, *and* "only show active sources" all in one filter, no separate
device-state API needed. The Electron app also polls `/devices` every 3s
(paused while capturing) and diffs by device name, not index — plugging in
a new device updates the dropdown live without restarting, and the current
selection survives the refresh as long as that device is still present.

## Latency

An attempt was made to cut the silence-commit wait (`SILENCE_COMMIT_SECONDS`
0.7s → 0.35s) to reduce the delay between finishing speaking and the result
landing. **Reverted** — committing that eagerly cut utterances off too
early, giving whisper less context per call, which measurably hurt
transcription accuracy. Timing constants are back to the milestone 1/2
defaults (see Configuration below); latency should be tuned via
`WHISPER_BEAM_SIZE` or a smaller `WHISPER_MODEL_SIZE` instead, since those
don't carry the same accuracy cost.

`transcriber.py` warns in the log (`Slow transcription: ...`) whenever a
single whisper call takes over 1s — worth checking that log if latency
feels off, since it points at model/hardware speed rather than the
buffering logic. `vad_filter=True` on the whisper call is load-bearing for
speed, not just accuracy — disabling it was tested and made marginal-audio
transcription 10-50x slower (Whisper can loop/hallucinate on non-speech
without it), so leave it on.

**Benchmarked on this dev machine (12-core CPU, no working GPU)** with a
real synthesized speech clip (Windows SAPI TTS, not silence/noise) to get
honest numbers instead of guessing:

| Change | Result |
|---|---|
| `medium.en` model (tried for accuracy) | ~9-10s to transcribe a 3s utterance — 3x realtime. **Reverted** — would make live captioning and reference detection lag multiple seconds behind speech |
| `beam_size` 1 vs 3 vs 5 | No meaningful difference (~3.4-4s each) — beam width isn't the bottleneck here, so it's free to keep at `5` for the small accuracy edge |
| Explicit `cpu_threads=8` (`WHISPER_CPU_THREADS`) | ~20-25% faster than ctranslate2's own default thread count (~3.5-4s → ~2.9-3.1s for a 3s utterance) — kept, no downside found |
| `initial_prompt` with Bible book names + KJV vocabulary | No latency cost (it's a text prompt, not more audio) — kept as a speculative accuracy aid; hasn't been isolated with real sermon audio, so its actual effect size is unconfirmed |

**Bottom line**: on this hardware, `small.en` decodes at roughly real-time
speed (≈1s of compute per 1s of speech) even after tuning. A 3-4 word
command ("next verse") should feel snappy; a full citation ("turn to John
chapter 3 verse 16", ~3s of audio) realistically costs ~3s of transcription
on top of the ~0.7s silence-commit wait — sub-1-second total latency for
that isn't achievable on this specific machine without either a smaller/less
accurate model, faster hardware, or a GPU (this machine's has no working
CUDA/cuBLAS runtime — see NFR-4). Worth re-running this same benchmark
directly on the actual production PC once it's available, since its CPU may
differ meaningfully from this dev machine.

## Configuration

Backend behavior is tunable via environment variables (see `backend/transcriber.py`):

| Variable | Default | Purpose |
|---|---|---|
| `WHISPER_MODEL_SIZE` | `small.en` | faster-whisper model size — English-only (`.en`) variants are more accurate than multilingual for sermon audio at the same speed. Bigger = more accurate, slower: `tiny.en` → `base.en` → `small.en` → `medium.en` → `large-v3` |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda`. Do **not** use `auto` unless CUDA/cuBLAS is confirmed working — it silently crashes the transcription thread on machines with a GPU but no working CUDA runtime |
| `WHISPER_COMPUTE_TYPE` | `int8` | Precision/quantization for CPU speed vs. accuracy tradeoff |
| `WHISPER_BEAM_SIZE` | `5` | Benchmarked no meaningful speed difference vs. `1` on this machine, so left at `5` for the accuracy edge — worth re-checking on other hardware |
| `WHISPER_CPU_THREADS` | `min(8, cpu_count)` | Explicit thread count for ctranslate2 — measured faster than leaving it unset. Tune per-machine if CPU core count differs a lot from 8-12 |
| `SILENCE_RMS_THRESHOLD` | `0.008` | Energy level below which audio counts as silence (the MVP's VAD). Raise if background noise is triggering false speech detection; lower if quiet speech isn't being picked up |
| `TICK_SECONDS` | `0.5` | How often the STT loop polls for new audio |
| `SILENCE_COMMIT_SECONDS` | `0.7` | How long a silence run must last before the current utterance is finalized. A lower value was tried for latency and reverted — it cut utterances off too early and hurt accuracy (see Latency below) |
| `PARTIAL_REFRESH_SECONDS` | `1.5` | How often the live partial line re-transcribes while still speaking |
| `MAX_UTTERANCE_SECONDS` | `20.0` | Hard cap forcing a commit even without a silence gap (long run-on sentences) |

If transcription lags on the real production PC, drop to `base.en` or `tiny.en`
first, or lower `WHISPER_BEAM_SIZE` to `1` — NFR-4 flags that hardware should
be validated against the actual production PC before rollout.

## Distribution

`package.ps1` builds a clean zip for moving WordScroll to another PC:

```powershell
powershell -ExecutionPolicy Bypass -File package.ps1
```

It produces `WordScroll-<date>.zip` containing only what's actually needed
(source, bundled Bible data, `install.ps1`, the icon) — never `backend/venv`
or `app/node_modules` (both machine-specific, recreated fresh by
`install.ps1`), and never `backend/data` (this PC's own saved favorites/
history/theme — a new install should start clean, not inherit it).

**Moving it**: no server or account is required — drop the zip on a USB
drive, sync it through OneDrive, or send it directly PC-to-PC with Windows'
built-in Nearby Sharing (right-click the file → Share → Nearby Sharing, if
both machines have Bluetooth or are on the same Wi-Fi). On the target PC:
unzip anywhere, then right-click `install.ps1` → "Run with PowerShell" —
same one-time setup as "Setup (production PC)" above.

**Updating an existing install**: unzip the new package *into* the same
folder the app already lives in (Windows' "Copy and Replace" merge — don't
delete the old folder first). `backend/data` isn't part of the package, so
it's simply left alone by the merge; nothing overwrites saved favorites/
history/theme. Then re-run `install.ps1` — it's idempotent (skips venv
creation if one already exists) and just re-syncs whatever dependencies
changed, which matters if an update added a new pip/npm package. The
Desktop shortcut is recreated pointing at the same `electron.exe`, so
nothing needs re-pinning.

## Packaging

There's deliberately no compiled `.exe`/installer for the backend. A
PyInstaller build was tried (freezing `run_server.py` + `faster-whisper`/
`ctranslate2`/`ndi-python` into a standalone onedir bundle) and it built
successfully, but Windows' Application Control blocked it outright on a
locked-down test machine ("An Application Control policy has blocked this
file") — with no code-signing certificate to fix that, and no reason to
believe every future production PC will be more permissive.

Comparing against BibleShow (a similar existing tool) confirmed this isn't
inherent to "unsigned .exe" — BibleShow's own unsigned `.exe` ran fine on
the same machine. The actual culprit is PyInstaller specifically: its
bootloader unpacks/loads code at runtime in a pattern that closely
resembles malware droppers, which is a well-known source of false-positive
flags even for entirely legitimate PyInstaller apps.

The fix was to stop fighting that heuristic rather than trying to bypass
it: `install.ps1` sets up the app and points the Desktop shortcut straight
at `electron.exe`, the same binary used in development — nothing new and
unsigned is ever created, so there's nothing for Application Control to
flag. See "Setup (production PC)" above.

If a real installer is wanted later despite this, the more promising path
is MSIX packaging (`electron-builder`'s `appx` target) — it has its own
trust model separate from raw-`.exe` SmartScreen/Application Control, and a
self-signed certificate only needs one manual one-time "trust this
publisher" step per machine rather than a paid CA certificate. It's real
added work, though: MSIX runs in a lightly virtualized filesystem, so
`backend/app_paths.py`'s "write data next to the .exe" logic would need
adjusting to use the app's designated MSIX data folder instead.
