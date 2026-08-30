"""
Milestone 1: local speech-to-text loop.

Runs on a background thread, pulling newly captured audio from the rolling
buffer, growing an "utterance" while speech continues, and periodically
re-transcribing it so the UI can show a live partial line. A short run of
low-energy audio (silence) commits the current utterance as final and starts
a new one. This is a simple energy-based VAD for MVP purposes — accurate
enough to prove the pipeline; Phase 2+ can swap in webrtcvad/Silero if the
real-world false-trigger rate on sermon audio needs tightening.
"""
import logging
import os
import sys
import threading
import time
import types
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

# faster_whisper unconditionally imports PyAV (`av`) at module load, purely
# for its decode_audio() helper — used only when transcribe() is given a
# file path/bytes instead of a numpy array (see faster_whisper/transcribe.py:
# `if not isinstance(audio, np.ndarray): audio = decode_audio(...)`).
# audio_capture.py already captures raw PCM straight from sounddevice, so
# _transcribe() below always passes a numpy array — decode_audio() and thus
# real PyAV usage never happens in this app. That matters because PyAV
# bundles its own compiled FFmpeg DLLs, which Windows Application Control
# (WDAC) can block on a locked-down machine even though python.exe/uvicorn
# run fine — this crashed the backend on exactly such a machine with
# "ImportError: DLL load failed... Application Control policy has blocked
# this file" the moment faster_whisper was imported, despite PyAV's actual
# decoding never being reached. A stub module satisfies the unconditional
# `import av` so startup survives there too; real PyAV is still used
# normally wherever it isn't blocked.
try:
    import av  # noqa: F401
except Exception:
    logging.getLogger("bible-transcriber").warning(
        "PyAV unavailable (%s) - continuing without it; this app never calls "
        "its decode_audio() path since audio is always captured as raw PCM.",
        sys.exc_info()[1],
    )
    sys.modules["av"] = types.ModuleType("av")

from faster_whisper import WhisperModel

from audio_capture import AudioCapture, SAMPLE_RATE
from bible_books import BOOKS

# Biases Whisper's decoding toward scripture-reading vocabulary it wouldn't
# otherwise favor — book names, KJV-era diction — without costing any extra
# latency (it's a text prompt, not more audio to process). This is the
# single highest-value, lowest-risk accuracy lever available short of a
# bigger model: proper nouns and archaic words are exactly what a generic
# speech model gets wrong most often.
_BOOK_NAMES = ", ".join(b.canonical for b in BOOKS)
INITIAL_PROMPT = (
    "A sermon in a church service, reading and preaching from the King James Bible. "
    "Scripture references like John 3:16, Romans chapter 8 verse 28, and Genesis 1:1 are cited often. "
    f"Books of the Bible: {_BOOK_NAMES}. "
    "Common words: thee, thou, thy, thine, hath, doth, shalt, verily, "
    "begotten, whosoever, righteousness, salvation, repentance, covenant, gospel, disciples."
)

# English-only variant — noticeably more accurate than the multilingual model
# at the same speed, since sermon audio is English.
# medium.en was tried for accuracy and reverted: benchmarked on this machine,
# it took ~9-10s of CPU time to transcribe a 3s utterance — 3x realtime,
# which would make live captioning and reference detection lag several
# seconds behind speech. small.en transcribes in a fraction of real time
# (see the benchmark note in the module docstring's history). If the actual
# production PC has meaningfully more CPU headroom than this dev machine,
# medium.en is worth re-testing there specifically — set WHISPER_MODEL_SIZE.
MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small.en")
# Default to CPU rather than "auto": ctranslate2 will happily pick CUDA if it
# *sees* an NVIDIA GPU even when the machine's CUDA/cuBLAS runtime isn't
# properly installed, which crashes the worker thread on first transcribe.
# Set WHISPER_DEVICE=cuda explicitly once GPU support is confirmed working.
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
BEAM_SIZE = int(os.environ.get("WHISPER_BEAM_SIZE", "5"))
# ctranslate2's own default thread count under-uses available cores — pinning
# this explicitly measured ~20-25% faster transcription on the dev machine
# (12 cores) than leaving it unset. 8 leaves headroom for audio capture / NDI
# / the UI event loop rather than claiming every core; tune per-machine.
CPU_THREADS = int(os.environ.get("WHISPER_CPU_THREADS", str(min(8, os.cpu_count() or 4))))

TICK_SECONDS = float(os.environ.get("TICK_SECONDS", "0.5"))
PARTIAL_REFRESH_SECONDS = float(os.environ.get("PARTIAL_REFRESH_SECONDS", "1.5"))
SILENCE_RMS_THRESHOLD = float(os.environ.get("SILENCE_RMS_THRESHOLD", "0.008"))
# Reverted from a 0.35s experiment: committing that eagerly cut utterances
# off too early, giving whisper less context per call and measurably hurting
# accuracy. Latency should be tuned via WHISPER_BEAM_SIZE/model size instead
# of shrinking this, since this one has a direct accuracy cost.
SILENCE_COMMIT_SECONDS = float(os.environ.get("SILENCE_COMMIT_SECONDS", "0.7"))
MAX_UTTERANCE_SECONDS = float(os.environ.get("MAX_UTTERANCE_SECONDS", "20.0"))
MIN_UTTERANCE_SECONDS = float(os.environ.get("MIN_UTTERANCE_SECONDS", "0.4"))
# Partial re-transcription only looks at the tail of the growing utterance,
# not the whole thing. Without this cap, each partial re-transcribes the
# *entire* utterance so far (this loop is single-threaded and blocking), so
# for a long run-on sentence with no pause, the per-call cost keeps growing
# with the utterance — each call takes longer than the last, which delays
# the loop from ever noticing the silence gap that would commit it, which
# lets the utterance grow even more. That snowball is what turns an
# expected ~3-4s citation lag into 12s+ for a full verse read aloud without
# a breath. The final commit still transcribes the complete utterance (full
# accuracy, unaffected) — this only bounds the cost of the live preview.
PARTIAL_WINDOW_SECONDS = float(os.environ.get("PARTIAL_WINDOW_SECONDS", "8.0"))


def _tail_audio(chunks: list[np.ndarray], max_seconds: float) -> np.ndarray:
    """Concatenate only the most recent max_seconds of a chunk list, without
    materializing (and re-scanning) the full growing utterance every call."""
    max_samples = int(max_seconds * SAMPLE_RATE)
    total = 0
    tail: list[np.ndarray] = []
    for chunk in reversed(chunks):
        tail.append(chunk)
        total += len(chunk)
        if total >= max_samples:
            break
    audio = np.concatenate(list(reversed(tail)))
    return audio[-max_samples:] if len(audio) > max_samples else audio


@dataclass
class TranscriptSegment:
    text: str
    is_final: bool
    started_at: float
    updated_at: float


class TranscriptionEngine:
    def __init__(self, on_segment: Callable[[TranscriptSegment], None]):
        self._on_segment = on_segment
        self._model: Optional[WhisperModel] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._capture: Optional[AudioCapture] = None

    def _ensure_model(self) -> WhisperModel:
        if self._model is None:
            try:
                # Once the model's already cached from a prior run, skip the
                # network entirely — faster_whisper's default behavior tries
                # to check Hugging Face for a newer revision on every single
                # launch before falling back to the local cache, which is
                # fine on a fast connection but adds a real delay (a slow
                # DNS/connect timeout, not an instant failure) at every
                # startup on a venue with no or flaky internet (NFR-2). This
                # tries the fully-offline path first; only reaches the
                # network-enabled fallback below on a genuine first run,
                # when there's nothing cached yet to load offline.
                self._model = WhisperModel(
                    MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE, cpu_threads=CPU_THREADS,
                    local_files_only=True,
                )
            except Exception:
                self._model = WhisperModel(
                    MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE, cpu_threads=CPU_THREADS
                )
        return self._model

    @property
    def model_ready(self) -> bool:
        return self._model is not None

    def preload(self) -> None:
        """Load (and if needed, download) the model ahead of time so the first
        Start click doesn't have to wait on it."""
        self._ensure_model()

    def start(self, capture: AudioCapture) -> None:
        if self._thread is not None:
            return
        self._ensure_model()  # load eagerly so first utterance isn't slow
        self._capture = capture
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self._capture = None

    def _transcribe(self, samples: np.ndarray) -> str:
        model = self._ensure_model()
        t0 = time.time()
        segments, _info = model.transcribe(
            samples,
            language="en",
            vad_filter=True,
            beam_size=BEAM_SIZE,
            condition_on_previous_text=False,
            initial_prompt=INITIAL_PROMPT,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        elapsed = time.time() - t0
        if elapsed > 1.0:
            # Whisper occasionally takes multiple seconds on marginal audio
            # (noise/breath mistaken for speech-ish) — worth knowing when
            # tuning latency, since this dwarfs every other delay in the loop.
            logging.getLogger("bible-transcriber").warning(
                "Slow transcription: %.2fs for %.2fs of audio", elapsed, len(samples) / SAMPLE_RATE
            )
        return text

    def _run(self) -> None:
        assert self._capture is not None
        buf = self._capture.buffer
        log = logging.getLogger("bible-transcriber")

        read_pos = buf.total_written
        utterance_chunks: list[np.ndarray] = []
        utterance_started_at: Optional[float] = None
        silence_seconds = 0.0
        seconds_since_partial = 0.0

        while not self._stop_event.is_set():
            time.sleep(TICK_SECONDS)

            new_audio, read_pos = buf.read_since(read_pos)
            if len(new_audio) == 0:
                continue

            rms = float(np.sqrt(np.mean(np.square(new_audio))))
            chunk_seconds = len(new_audio) / SAMPLE_RATE

            if rms < SILENCE_RMS_THRESHOLD:
                silence_seconds += chunk_seconds
            else:
                silence_seconds = 0.0
                utterance_chunks.append(new_audio)
                if utterance_started_at is None:
                    utterance_started_at = time.time()

            has_utterance = bool(utterance_chunks)
            utterance_len_seconds = (
                sum(len(c) for c in utterance_chunks) / SAMPLE_RATE
                if has_utterance
                else 0.0
            )

            should_commit = has_utterance and (
                (silence_seconds >= SILENCE_COMMIT_SECONDS
                 and utterance_len_seconds >= MIN_UTTERANCE_SECONDS)
                or utterance_len_seconds >= MAX_UTTERANCE_SECONDS
            )

            try:
                if should_commit:
                    audio = np.concatenate(utterance_chunks)
                    text = self._transcribe(audio)
                    if text:
                        self._on_segment(
                            TranscriptSegment(
                                text=text,
                                is_final=True,
                                started_at=utterance_started_at or time.time(),
                                updated_at=time.time(),
                            )
                        )
                elif has_utterance:
                    seconds_since_partial += chunk_seconds
                    if seconds_since_partial >= PARTIAL_REFRESH_SECONDS:
                        audio = _tail_audio(utterance_chunks, PARTIAL_WINDOW_SECONDS)
                        text = self._transcribe(audio)
                        if text:
                            self._on_segment(
                                TranscriptSegment(
                                    text=text,
                                    is_final=False,
                                    started_at=utterance_started_at or time.time(),
                                    updated_at=time.time(),
                                )
                            )
                        seconds_since_partial = 0.0
            except Exception:
                # A single bad chunk shouldn't take down the whole live loop —
                # log it and keep listening rather than silently going deaf.
                log.exception("Transcription of current utterance failed — discarding it")
                should_commit = True  # fall through to the reset below

            if should_commit:
                utterance_chunks = []
                utterance_started_at = None
                silence_seconds = 0.0
                seconds_since_partial = 0.0
