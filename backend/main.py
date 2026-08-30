"""
Milestone 1 backend: list audio devices, start/stop capture+transcription,
and stream live transcript segments to connected clients over a WebSocket.

Run with:  uvicorn main:app --host 127.0.0.1 --port 8765
"""
import asyncio
import io
import logging
import re
import time
import uuid
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image as PILImage
from pydantic import BaseModel, field_validator

import favorites_store
import history_store
import queue_store
import theme_store
import theme_templates
from app_paths import resource_dir
from audio_capture import AudioCapture, RollingAudioBuffer, list_input_devices, refresh_device_list
from bible_books import BOOKS
from bible_text import get_chapter_verses, get_last_verse_number, get_verse_text, preload_all, search_keyword
from display_renderer import render_blank_frame, render_display_frame
from ndi_output import NdiOutput
from recitation_matcher import match_recitation
from reference_parser import (
    DetectedReference,
    detect_bare_book,
    detect_bare_verse_jump,
    detect_next_verse_command,
    detect_previous_verse_command,
    detect_references,
)
from transcriber import TranscriptionEngine, TranscriptSegment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bible-transcriber")

app = FastAPI(title="AI Bible Transcriber — Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local-only desktop app; no external exposure
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_overlay_static(request, call_next):
    """OBS/vMix's Browser Source (and any browser) will otherwise cache
    overlay.css/overlay.js indefinitely — a future update to the overlay's
    look would silently not apply until the operator manually clears the
    browser cache. Static theme images (/theme-assets) are fine to cache —
    each upload gets a fresh generated filename, so a cached copy is never
    stale."""
    response = await call_next(request)
    if request.url.path.startswith("/overlay"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

_buffer = RollingAudioBuffer()
_capture: Optional[AudioCapture] = None
_engine: Optional[TranscriptionEngine] = None
_clients: set[WebSocket] = set()
_loop: Optional[asyncio.AbstractEventLoop] = None
_display_state: Optional[dict] = None  # current on-screen verse, or None if cleared
_ndi: Optional[NdiOutput] = None

# Recent finalized transcript text, so a natural speech pause — "...chapter 3
# [breath] verse 16" — that our silence-based commit splits into two final
# segments doesn't cost us the reference. Detection runs on the whole window,
# not just the newest segment in isolation.
_RECENT_FINAL_WINDOW_SECONDS = 8.0
_recent_finals: list[tuple[float, str]] = []


class StartRequest(BaseModel):
    device_index: int


class DisplayRequest(BaseModel):
    book: str
    chapter: int
    verse_start: Optional[int] = None
    verse_end: Optional[int] = None
    translation: str = "KJV"


class MoveRequest(BaseModel):
    direction: str  # "up" or "down"


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeUpdate(BaseModel):
    fontFamily: Optional[str] = None
    verseColor: Optional[str] = None
    referenceColor: Optional[str] = None
    verseFontSize: Optional[int] = None
    referenceFontSize: Optional[int] = None
    textPosition: Optional[str] = None
    textAlign: Optional[str] = None
    referencePlacement: Optional[str] = None
    backgroundStyle: Optional[str] = None
    backgroundColor: Optional[str] = None
    backgroundOpacity: Optional[float] = None
    backgroundImage: Optional[str] = None  # filename, or "" to clear
    layout: Optional[str] = None
    verseMarginX: Optional[int] = None
    verseMarginY: Optional[int] = None
    referenceMargin: Optional[int] = None
    shadowIntensity: Optional[str] = None

    @field_validator("verseColor", "referenceColor", "backgroundColor")
    @classmethod
    def _validate_hex_color(cls, v):
        if v is not None and not _HEX_COLOR_RE.match(v):
            raise ValueError("must be a #RRGGBB hex color")
        return v

    @field_validator("verseFontSize")
    @classmethod
    def _validate_verse_font_size(cls, v):
        if v is not None and not (16 <= v <= 160):
            raise ValueError("verseFontSize must be between 16 and 160")
        return v

    @field_validator("referenceFontSize")
    @classmethod
    def _validate_reference_font_size(cls, v):
        if v is not None and not (10 <= v <= 80):
            raise ValueError("referenceFontSize must be between 10 and 80")
        return v

    @field_validator("textPosition")
    @classmethod
    def _validate_text_position(cls, v):
        if v is not None and v not in ("top", "center", "bottom"):
            raise ValueError("textPosition must be 'top', 'center', or 'bottom'")
        return v

    @field_validator("textAlign")
    @classmethod
    def _validate_text_align(cls, v):
        if v is not None and v not in ("center", "left"):
            raise ValueError("textAlign must be 'center' or 'left'")
        return v

    @field_validator("referencePlacement")
    @classmethod
    def _validate_reference_placement(cls, v):
        if v is not None and v not in ("above", "below"):
            raise ValueError("referencePlacement must be 'above' or 'below'")
        return v

    @field_validator("backgroundStyle")
    @classmethod
    def _validate_background_style(cls, v):
        if v is not None and v not in ("none", "box", "image"):
            raise ValueError("backgroundStyle must be 'none', 'box', or 'image'")
        return v

    @field_validator("layout")
    @classmethod
    def _validate_layout(cls, v):
        if v is not None and v not in ("lower-third", "full-frame"):
            raise ValueError("layout must be 'lower-third' or 'full-frame'")
        return v

    @field_validator("verseMarginX", "verseMarginY", "referenceMargin")
    @classmethod
    def _validate_margin(cls, v):
        if v is not None and not (0 <= v <= 160):
            raise ValueError("margin must be between 0 and 160")
        return v

    @field_validator("backgroundOpacity")
    @classmethod
    def _validate_background_opacity(cls, v):
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("backgroundOpacity must be between 0.0 and 1.0")
        return v

    @field_validator("shadowIntensity")
    @classmethod
    def _validate_shadow_intensity(cls, v):
        if v is not None and v not in ("none", "normal", "strong"):
            raise ValueError("shadowIntensity must be 'none', 'normal', or 'strong'")
        return v


def _ref_key(r) -> str:
    return f"{r.book}|{r.chapter}|{r.verse_start}|{r.verse_end}"


_last_broadcast_ref_key: Optional[str] = None


def _on_segment(segment: TranscriptSegment) -> None:
    """Called from the transcription worker thread — hop back to the event loop."""
    global _last_broadcast_ref_key
    if _loop is None:
        return
    segment_type = "final" if segment.is_final else "partial"
    payload = {
        "type": segment_type,
        "text": segment.text,
        "startedAt": segment.started_at,
        "updatedAt": segment.updated_at,
    }
    asyncio.run_coroutine_threadsafe(_broadcast(payload), _loop)

    if segment.is_final:
        now = time.time()
        _recent_finals.append((now, segment.text))
        while _recent_finals and now - _recent_finals[0][0] > _RECENT_FINAL_WINDOW_SECONDS:
            _recent_finals.pop(0)
        detection_text = " ".join(text for _, text in _recent_finals)
    else:
        detection_text = segment.text

    refs = detect_references(detection_text)
    # Applied to both partial and final segments — a still-forming utterance
    # re-transcribes the same trailing window on every partial refresh (see
    # transcriber.py's PARTIAL_WINDOW_SECONDS), and the final path has its
    # own analogous overlap via the _recent_finals rolling window just
    # below. Either way, without this the same reference would re-broadcast
    # (and re-render as a new card, or re-auto-push) repeatedly for as long
    # as it stays inside whichever window is currently in play.
    fresh_refs = [r for r in refs if _ref_key(r) != _last_broadcast_ref_key]
    if fresh_refs:
        _last_broadcast_ref_key = _ref_key(fresh_refs[-1])

    if fresh_refs:
        ref_payload = {
            "type": "reference",
            "segmentType": segment_type,
            "references": [
                {
                    "book": r.book,
                    "chapter": r.chapter,
                    "verseStart": r.verse_start,
                    "verseEnd": r.verse_end,
                    "rawText": r.raw_text,
                    "confidence": r.confidence,
                    # The actual bundled scripture text, so a card shows what
                    # the verse really says — not just what the transcript
                    # heard — which matters most for the low-confidence ones
                    # the operator has to judge before approving.
                    "previewText": get_verse_text(r.book, r.chapter, r.verse_start or 1, r.verse_end),
                }
                for r in fresh_refs
            ],
        }
        asyncio.run_coroutine_threadsafe(_broadcast(ref_payload), _loop)

    # High-confidence explicit references auto-push straight to output
    # (FR-5.1) on BOTH partial and final segments — waiting for is_final
    # here used to hurt continuous, pause-free preaching specifically: an
    # utterance can run for up to MAX_UTTERANCE_SECONDS (20s) before it
    # finalizes, so a reference cited mid-sentence sat detected-but-not-
    # pushed for up to that long even though it showed up in the pending
    # panel almost immediately. Partial transcription already re-runs every
    # PARTIAL_REFRESH_SECONDS (~1.5s) against a bounded trailing window
    # (see transcriber.py), so pushing from partials too brings worst-case
    # latency back down near that, in line with NFR-1's <2s target,
    # regardless of how long the sentence runs on. Low-confidence explicit
    # refs still only ever reach the pending panel (FR-5.2) — that gating
    # already happens above, since `refs`/`fresh_refs` includes them but
    # this filters to "high" only.
    high_confidence = [r for r in fresh_refs if r.confidence == "high"]
    if high_confidence:
        r = high_confidence[-1]
        asyncio.run_coroutine_threadsafe(
            _apply_display(r.book, r.chapter, r.verse_start, r.verse_end), _loop
        )

    if not segment.is_final:
        return  # next/previous-verse commands, bare-verse jumps, and recitation matching all need a finished utterance — see their own comments below

    if high_confidence:
        pass  # already auto-pushed above
    elif detect_next_verse_command(segment.text):
        asyncio.run_coroutine_threadsafe(_advance_verse(), _loop)
    elif detect_previous_verse_command(segment.text):
        asyncio.run_coroutine_threadsafe(_retreat_verse(), _loop)
    elif fresh_refs:
        pass  # a low-confidence explicit reference was already broadcast above — nothing more to do
    else:
        # Mid-reading, a preacher often says just "verse 17" without
        # repeating the book/chapter — jump within whatever's already live.
        bare_verse = detect_bare_verse_jump(segment.text)
        if bare_verse is not None and _display_state is not None and _display_state.get("active"):
            book = _display_state["book"]
            chapter = _display_state["chapter"]
            asyncio.run_coroutine_threadsafe(_apply_display(book, chapter, bare_verse, None), _loop)
        else:
            # No citation, no navigation command — try matching the utterance
            # against the full translation in case it's a verse recited or
            # paraphrased from memory (FR-4.1/4.2). Always low confidence
            # (FR-4.3): recitation matching runs the same rapidfuzz call
            # against ~31k verses on every plain sentence anyone says, so
            # false positives are expected — that's exactly why these never
            # auto-push, only ever show up for the operator to confirm.
            match = match_recitation(segment.text)
            if match is not None:
                key = f"{match['book']}|{match['chapter']}|{match['verse']}|None"
                if key != _last_broadcast_ref_key:
                    _last_broadcast_ref_key = key
                    ref_payload = {
                        "type": "reference",
                        "segmentType": segment_type,
                        "references": [
                            {
                                "book": match["book"],
                                "chapter": match["chapter"],
                                "verseStart": match["verse"],
                                "verseEnd": None,
                                "rawText": segment.text.strip(),
                                "confidence": "low",
                                "previewText": match["text"],  # the actual verse, not what was recited
                            }
                        ],
                    }
                    asyncio.run_coroutine_threadsafe(_broadcast(ref_payload), _loop)


async def _apply_display(book: str, chapter: int, verse_start: Optional[int], verse_end: Optional[int], translation: str = "KJV") -> Optional[dict]:
    """Looks up verse text and pushes it to every output (Electron UI, HTML
    overlay, NDI). Returns the new display state, or None if the reference
    doesn't resolve to real verse text.

    A chapter-only reference (verse_start is None) defaults to verse 1
    rather than dumping the whole chapter onto the screen — the Chapter
    Navigator (which reacts to any display push, including this one) is
    where the operator browses the rest of the chapter."""
    global _display_state
    if verse_start is None:
        verse_start = 1
    text = get_verse_text(book, chapter, verse_start, verse_end)
    if text is None:
        return None

    reference = f"{book} {chapter}"
    if verse_start is not None:
        reference += f":{verse_start}"
        if verse_end is not None:
            reference += f"-{verse_end}"

    _display_state = {
        "active": True,
        "book": book,
        "chapter": chapter,
        "verseStart": verse_start,
        "verseEnd": verse_end,
        "translation": translation,
        "reference": reference,
        "text": text,
    }
    if _ndi is not None and _ndi.available:
        _ndi.set_frame(render_display_frame(reference, translation, text))
    await _broadcast({"type": "display", **_display_state})
    entry = history_store.record(_display_state)
    await _broadcast({"type": "history_add", "entry": entry})
    logger.info("Display pushed: %s", reference)
    return _display_state


async def _advance_verse() -> bool:
    """Advances the currently displayed reference by one verse, rolling into
    the next chapter if the current chapter has run out of verses. Shared by
    the spoken "next verse" command and the manual next-verse hotkey."""
    if _display_state is None or not _display_state.get("active"):
        logger.info("Advance-verse requested, but nothing is currently displayed — ignoring")
        return False

    book = _display_state["book"]
    chapter = _display_state["chapter"]
    current_verse = _display_state["verseEnd"] or _display_state["verseStart"]
    if current_verse is None:
        logger.info("Advance-verse requested, but the current display has no verse number — ignoring")
        return False

    if await _apply_display(book, chapter, current_verse + 1, None) is not None:
        return True
    # Ran off the end of the chapter — try verse 1 of the next chapter.
    return await _apply_display(book, chapter + 1, 1, None) is not None


async def _retreat_verse() -> bool:
    """Moves the currently displayed reference back one verse, rolling into
    the last verse of the previous chapter at a chapter boundary. Symmetric
    counterpart to _advance_verse(), driven by the previous-verse hotkey."""
    if _display_state is None or not _display_state.get("active"):
        logger.info("Retreat-verse requested, but nothing is currently displayed — ignoring")
        return False

    book = _display_state["book"]
    chapter = _display_state["chapter"]
    current_verse = _display_state["verseStart"]
    if current_verse is None:
        logger.info("Retreat-verse requested, but the current display has no verse number — ignoring")
        return False

    if current_verse > 1:
        return await _apply_display(book, chapter, current_verse - 1, None) is not None

    if chapter <= 1:
        return False  # already at the first verse of the book — no previous book support yet

    last_verse = get_last_verse_number(book, chapter - 1)
    if last_verse is None:
        return False
    return await _apply_display(book, chapter - 1, last_verse, None) is not None


async def _broadcast(payload: dict) -> None:
    dead = []
    for ws in _clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)


async def _level_broadcaster() -> None:
    """Streams the current mic input level ~15x/sec so the UI can render a live VU meter."""
    while True:
        await asyncio.sleep(1 / 15)
        if _capture is not None and _capture.is_running and _clients:
            await _broadcast({"type": "level", "level": _capture.level})


@app.on_event("startup")
async def on_startup() -> None:
    global _loop, _engine, _ndi
    _loop = asyncio.get_running_loop()
    _engine = TranscriptionEngine(on_segment=_on_segment)
    asyncio.create_task(_level_broadcaster())
    # Load (and, on first run, download) the whisper model in the background
    # so it's ready before the operator clicks Start, instead of blocking that click.
    _loop.run_in_executor(None, _engine.preload)

    _ndi = NdiOutput()
    if _ndi.available:
        _ndi.start()  # starts pushing blank frames immediately so the NDI source is discoverable right away

    _loop.run_in_executor(None, preload_all)  # needed for keyword search to scan the whole Bible
    _loop.run_in_executor(None, lambda: match_recitation("warm the recitation matcher cache"))


@app.on_event("shutdown")
async def on_shutdown() -> None:
    if _ndi is not None:
        _ndi.stop()


@app.get("/devices")
def get_devices():
    # Only safe to force PortAudio to re-scan (see refresh_device_list's
    # docstring) when nothing is actively capturing through it — the
    # renderer already pauses its /devices polling while capturing, but
    # this guards the endpoint itself too, since nothing else prevents a
    # direct call from hitting this mid-capture.
    if _capture is None or not _capture.is_running:
        refresh_device_list()
    return {"devices": list_input_devices()}


@app.get("/status")
def get_status():
    return {
        "capturing": _capture is not None and _capture.is_running,
        "device_index": _capture.device_index if _capture else None,
        "model_ready": _engine.model_ready if _engine is not None else False,
        "ndi_available": _ndi.available if _ndi is not None else False,
        "ndi_error": _ndi.error if _ndi is not None else None,
    }


@app.post("/start")
def start(req: StartRequest):
    global _capture, _last_broadcast_ref_key
    if _capture is not None and _capture.is_running:
        _capture.stop()
        _engine.stop()

    _recent_finals.clear()
    _last_broadcast_ref_key = None

    candidate = AudioCapture(device_index=req.device_index, buffer=_buffer)
    try:
        candidate.start()
    except Exception as exc:
        logger.warning("Failed to start capture on device %s: %s", req.device_index, exc)
        raise HTTPException(
            status_code=400,
            detail=f"Could not open this audio device: {exc}",
        )

    _capture = candidate
    _engine.start(_capture)
    logger.info("Started capture on device %s", req.device_index)
    return {"ok": True}


@app.post("/stop")
def stop():
    global _capture
    if _capture is not None:
        _capture.stop()
    if _engine is not None:
        _engine.stop()
    _capture = None
    logger.info("Stopped capture")
    return {"ok": True}


def _reference_label(book: str, chapter: int, verse_start: Optional[int], verse_end: Optional[int]) -> str:
    label = f"{book} {chapter}"
    if verse_start is not None:
        label += f":{verse_start}"
        if verse_end is not None:
            label += f"-{verse_end}"
    return label


@app.get("/search/reference")
def search_reference(q: str):
    """FR-6.1: manual reference search — "John 3:16", "Romans 8", etc.
    Bypasses the detector entirely; the operator types it directly."""
    results = []
    refs = detect_references(q)
    if not refs:
        # Typing just a book name/alias/short-code with nothing else (e.g.
        # "php") has no chapter for detect_references() to find, so it
        # correctly returns nothing — that function is shared with live
        # speech detection, where a bare book mention with no chapter must
        # NOT auto-navigate. Manual search is different: someone who typed
        # only a short code clearly wants that book, so fall back to
        # chapter 1 rather than showing an empty result list.
        bare_book = detect_bare_book(q)
        if bare_book is not None:
            refs = [DetectedReference(book=bare_book, chapter=1, verse_start=None, verse_end=None, raw_text=q)]
    for r in refs:
        # Match what a click actually pushes (_apply_display defaults a
        # chapter-only reference to verse 1) so the preview isn't a whole-
        # chapter dump when the push itself will only be one verse.
        verse_start = r.verse_start if r.verse_start is not None else 1
        text = get_verse_text(r.book, r.chapter, verse_start, r.verse_end)
        if text is None:
            continue
        results.append(
            {
                "book": r.book,
                "chapter": r.chapter,
                "verseStart": verse_start,
                "verseEnd": r.verse_end,
                "reference": _reference_label(r.book, r.chapter, verse_start, r.verse_end),
                "text": text,
            }
        )
    return {"results": results}


@app.get("/search/keyword")
def search_keyword_endpoint(q: str):
    """FR-6.1: manual keyword/phrase search across the bundled translation."""
    if len(q.strip()) < 3:
        return {"results": []}
    matches = search_keyword(q, limit=50)
    results = [
        {
            "book": m["book"],
            "chapter": m["chapter"],
            "verseStart": m["verse"],
            "verseEnd": None,
            "reference": _reference_label(m["book"], m["chapter"], m["verse"], None),
            "text": m["text"],
        }
        for m in matches
    ]
    return {"results": results}


@app.get("/reference/short-codes")
def reference_short_codes():
    """The canonical one-per-book short reference code (see bible_books.py's
    Book.short_code) — e.g. "php" for Philippians, "phm" for Philemon.
    These work directly in the Reference search field and in live speech,
    same as any other alias. JSON for programmatic use; see
    /reference/short-codes.html for the operator-facing list."""
    return {"books": [{"book": b.canonical, "shortCode": b.short_code} for b in BOOKS]}


@app.get("/reference/short-codes.html", response_class=HTMLResponse)
def reference_short_codes_html():
    """Human-readable version of the same table, for Help > Reference Short
    Codes in the app menu — opened in the operator's default browser, where
    Ctrl+S / Ctrl+P give them a saved/printed copy without this app needing
    its own file-export plumbing."""
    rows = "".join(
        f"<tr><td>{b.canonical}</td><td><code>{b.short_code}</code></td></tr>" for b in BOOKS
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Reference Short Codes — AI Bible Transcriber</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #111318; color: #e8eaf0; padding: 32px; }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  p.hint {{ color: #8a8f9c; font-size: 13px; margin-top: 0; margin-bottom: 24px; }}
  table {{ border-collapse: collapse; width: 100%; max-width: 480px; }}
  th, td {{ text-align: left; padding: 6px 12px; border-bottom: 1px solid #2a2e38; font-size: 14px; }}
  th {{ color: #8a8f9c; font-weight: 600; }}
  code {{ background: #22262f; padding: 2px 6px; border-radius: 4px; color: #ffd166; }}
  @media print {{
    body {{ background: #fff; color: #000; }}
    code {{ background: none; color: #000; }}
  }}
</style>
</head>
<body>
<h1>Reference Short Codes</h1>
<p class="hint">Type any of these into the Reference search field (e.g. "php 4:13") — works in typed search and live speech detection alike.</p>
<table>
<thead><tr><th>Book</th><th>Short Code</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/chapter")
def get_chapter(book: str, chapter: int):
    """Powers the chapter navigator: every verse in a chapter, so the
    operator can jump to any verse in whatever's currently displayed without
    retyping a search — regardless of how that chapter got on screen
    (voice, search, or another chapter-nav click)."""
    verses = get_chapter_verses(book, chapter)
    if verses is None:
        raise HTTPException(status_code=404, detail="No such book/chapter")
    return {"book": book, "chapter": chapter, "verses": verses}


@app.post("/display/push")
async def display_push(req: DisplayRequest):
    state = await _apply_display(req.book, req.chapter, req.verse_start, req.verse_end, req.translation)
    if state is None:
        raise HTTPException(status_code=404, detail="No verse text found for that reference")
    return state


@app.post("/display/next")
async def display_next():
    """Advances to the next verse — the manual (hotkey) counterpart to the
    spoken "next verse" command. Both call the same _advance_verse()."""
    if not await _advance_verse():
        raise HTTPException(
            status_code=400,
            detail="Nothing is currently displayed, or it has no verse number to advance from.",
        )
    return _display_state


@app.post("/display/previous")
async def display_previous():
    """Moves back to the previous verse — the hotkey counterpart to advancing."""
    if not await _retreat_verse():
        raise HTTPException(
            status_code=400,
            detail="Nothing is currently displayed, already at the first verse, or it has no verse number.",
        )
    return _display_state


@app.post("/display/clear")
async def display_clear():
    global _display_state
    _display_state = {"active": False}
    if _ndi is not None and _ndi.available:
        _ndi.set_frame(render_blank_frame())
    await _broadcast({"type": "display", **_display_state})
    logger.info("Display cleared")
    return _display_state


@app.get("/display/state")
def display_state():
    return _display_state or {"active": False}


def _rerender_current_frame(theme: dict) -> None:
    """A theme edit should re-render whatever's already on screen immediately
    — not just future pushes — so the operator sees the change live."""
    if _ndi is not None and _ndi.available and _display_state is not None and _display_state.get("active"):
        _ndi.set_frame(render_display_frame(
            _display_state["reference"], _display_state["translation"], _display_state["text"], theme
        ))


@app.get("/theme")
def theme_get():
    return theme_store.for_overlay()


@app.get("/theme/fonts")
def theme_fonts():
    return {"fonts": theme_store.fonts()}


@app.get("/theme/layouts")
def theme_layouts():
    return {"layouts": theme_store.LAYOUT_PRESETS}


@app.post("/theme")
async def theme_update(req: ThemeUpdate):
    new_theme = theme_store.update(req.model_dump(exclude_none=True))
    _rerender_current_frame(new_theme)
    payload = theme_store.for_overlay(new_theme)
    await _broadcast({"type": "theme", "theme": payload})
    return payload


@app.post("/theme/reset")
async def theme_reset():
    new_theme = theme_store.reset()
    _rerender_current_frame(new_theme)
    payload = theme_store.for_overlay(new_theme)
    await _broadcast({"type": "theme", "theme": payload})
    return payload


_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_IMAGE_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


@app.post("/theme/background-image")
async def theme_upload_background_image(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image exceeds 10MB limit")
    try:
        img = PILImage.open(io.BytesIO(data))
        img.verify()
        ext = _IMAGE_EXTENSIONS.get(img.format, ".img")
    except Exception:
        raise HTTPException(status_code=400, detail="File is not a valid image")
    filename = f"{uuid.uuid4().hex}{ext}"
    (theme_store.THEME_ASSETS_DIR / filename).write_bytes(data)
    return {"filename": filename, "url": f"/theme-assets/{filename}"}


@app.get("/theme/templates")
def theme_templates_list():
    return {"templates": theme_templates.list_all()}


class TemplateCreate(BaseModel):
    name: str


@app.post("/theme/templates")
def theme_templates_create(req: TemplateCreate):
    template = theme_templates.create(req.name, theme_store.get())
    return template


@app.post("/theme/templates/{template_id}/apply")
async def theme_templates_apply(template_id: str):
    template = theme_templates.get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="No such template")
    new_theme = theme_store.update(template["theme"])
    _rerender_current_frame(new_theme)
    payload = theme_store.for_overlay(new_theme)
    await _broadcast({"type": "theme", "theme": payload})
    return payload


@app.delete("/theme/templates/{template_id}")
def theme_templates_delete(template_id: str):
    if not theme_templates.delete(template_id):
        raise HTTPException(status_code=404, detail="No such template")
    return {"ok": True}


@app.get("/history")
def history_list():
    return {"history": history_store.list_all()}


@app.post("/history/clear")
async def history_clear():
    history_store.clear()
    await _broadcast({"type": "history_cleared"})
    return {"history": []}


@app.get("/favorites")
def favorites_list():
    return {"favorites": favorites_store.list_all()}


@app.post("/favorites")
async def favorites_add(req: DisplayRequest):
    verse_start = req.verse_start if req.verse_start is not None else 1
    text = get_verse_text(req.book, req.chapter, verse_start, req.verse_end)
    if text is None:
        raise HTTPException(status_code=404, detail="No verse text found for that reference")
    reference = _reference_label(req.book, req.chapter, verse_start, req.verse_end)
    favorites_store.add(req.book, req.chapter, verse_start, req.verse_end, req.translation, text, reference)
    payload = {"type": "favorites", "favorites": favorites_store.list_all()}
    await _broadcast(payload)
    return payload


@app.delete("/favorites/{fav_id}")
async def favorites_remove(fav_id: str):
    if not favorites_store.remove(fav_id):
        raise HTTPException(status_code=404, detail="No such favorite")
    payload = {"type": "favorites", "favorites": favorites_store.list_all()}
    await _broadcast(payload)
    return payload


@app.get("/queue")
def queue_list():
    return {"queue": queue_store.list_all()}


@app.post("/queue")
async def queue_add(req: DisplayRequest):
    verse_start = req.verse_start if req.verse_start is not None else 1
    text = get_verse_text(req.book, req.chapter, verse_start, req.verse_end)
    if text is None:
        raise HTTPException(status_code=404, detail="No verse text found for that reference")
    reference = _reference_label(req.book, req.chapter, verse_start, req.verse_end)
    queue_store.add(req.book, req.chapter, verse_start, req.verse_end, req.translation, text, reference)
    payload = {"type": "queue", "queue": queue_store.list_all()}
    await _broadcast(payload)
    return payload


@app.delete("/queue/{item_id}")
async def queue_remove(item_id: str):
    if not queue_store.remove(item_id):
        raise HTTPException(status_code=404, detail="No such queue item")
    payload = {"type": "queue", "queue": queue_store.list_all()}
    await _broadcast(payload)
    return payload


@app.post("/queue/{item_id}/move")
async def queue_move(item_id: str, req: MoveRequest):
    if req.direction not in ("up", "down"):
        raise HTTPException(status_code=400, detail="direction must be 'up' or 'down'")
    if not queue_store.move(item_id, req.direction):
        raise HTTPException(status_code=400, detail="No such queue item, or already at that end")
    payload = {"type": "queue", "queue": queue_store.list_all()}
    await _broadcast(payload)
    return payload


@app.post("/queue/advance")
async def queue_advance():
    entry = queue_store.pop_first()
    if entry is None:
        raise HTTPException(status_code=400, detail="Queue is empty")
    state = await _apply_display(entry["book"], entry["chapter"], entry["verseStart"], entry["verseEnd"], entry["translation"])
    await _broadcast({"type": "queue", "queue": queue_store.list_all()})
    return state


@app.websocket("/ws/transcript")
async def ws_transcript(websocket: WebSocket):
    await websocket.accept()
    _clients.add(websocket)
    try:
        while True:
            # Client doesn't need to send anything; keep the connection open.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)


# Mounted last so it never shadows the API routes above. Add as an OBS Browser
# Source or vMix Web Browser input pointed at http://127.0.0.1:8765/overlay/
app.mount("/overlay", StaticFiles(directory=resource_dir("overlay"), html=True), name="overlay")
app.mount("/theme-assets", StaticFiles(directory=theme_store.THEME_ASSETS_DIR), name="theme-assets")
