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
import queue
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
import ctranslate2

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

def _cuda_available() -> bool:
    try:
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


# English-only variant — noticeably more accurate than the multilingual model
# at the same speed, since sermon audio is English.
# medium.en was tried on CPU and reverted: ~9-10s to transcribe a 3s
# utterance there, 3x realtime, which would make live captioning and
# reference detection lag several seconds behind speech. On a CUDA GPU it's a
# completely different picture — benchmarked at 40-56x realtime on an RTX
# 4050 — so the default follows whichever device this machine actually gets,
# rather than a single fixed choice for every machine.
_DEFAULT_DEVICE = "cuda" if _cuda_available() else "cpu"
MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE") or ("medium.en" if _DEFAULT_DEVICE == "cuda" else "small.en")
# ctranslate2 will happily try to use CUDA if it *sees* an NVIDIA GPU even
# when the machine's CUDA/cuDNN runtime isn't fully installed, which used to
# mean crashing the worker thread on first transcribe with no way back —
# _ensure_model() below now catches that and falls back to CPU/small.en
# instead of taking the whole engine down. Set WHISPER_DEVICE explicitly to
# override the auto-detected choice either way.
DEVICE = os.environ.get("WHISPER_DEVICE") or _DEFAULT_DEVICE
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE") or ("float16" if DEVICE == "cuda" else "int8")
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
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._capture: Optional[AudioCapture] = None
        # Finals are never dropped — order and completeness there is what
        # reference detection depends on. Partials are UI-preview-only, so
        # the queue holds at most the single freshest one: a partial that's
        # still waiting when a newer one is ready is stale and worth nothing
        # once it's transcribed, so it's replaced rather than queued behind.
        self._final_queue: "queue.Queue[tuple[np.ndarray, float]]" = queue.Queue()
        self._partial_queue: "queue.Queue[tuple[np.ndarray, float]]" = queue.Queue(maxsize=1)

    def _load_model(self, model_size: str, device: str, compute_type: str) -> WhisperModel:
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
            # when there's nothing cached yet to load offline. A genuine
            # device/runtime failure (e.g. CUDA present but its cuDNN
            # runtime broken) fails identically both ways, and is left to
            # propagate to _ensure_model()'s own device-level fallback
            # rather than being swallowed here.
            return WhisperModel(
                model_size, device=device, compute_type=compute_type, cpu_threads=CPU_THREADS,
                local_files_only=True,
            )
        except Exception:
            return WhisperModel(
                model_size, device=device, compute_type=compute_type, cpu_threads=CPU_THREADS
            )

    def _ensure_model(self) -> WhisperModel:
        if self._model is None:
            try:
                self._model = self._load_model(MODEL_SIZE, DEVICE, COMPUTE_TYPE)
            except Exception as exc:
                if DEVICE == "cuda":
                    # The GPU was detected (ctranslate2.get_cuda_device_count()
                    # > 0) but loading on it still failed — a missing/broken
                    # CUDA or cuDNN runtime, not actually no GPU. Falling back
                    # to the known-good CPU config keeps the app usable
                    # instead of leaving it permanently stuck with no model.
                    logging.getLogger("bible-transcriber").warning(
                        "Failed to load Whisper on CUDA (%s) — falling back to CPU/small.en", exc
                    )
                    self._model = self._load_model("small.en", "cpu", "int8")
                else:
                    raise
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
        # Two threads: _run() only does cheap, real-time chunk bookkeeping
        # (silence detection, utterance boundaries) and must never block on
        # Whisper — see _transcribe_worker()'s docstring for why that
        # blocking was silently losing entire utterances. The actual model
        # calls happen on this second thread instead, however far behind
        # they fall.
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._worker_thread = threading.Thread(target=self._transcribe_worker, daemon=True)
        self._worker_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=5)
        self._thread = None
        self._worker_thread = None
        self._capture = None
        with self._final_queue.mutex:
            self._final_queue.queue.clear()
        with self._partial_queue.mutex:
            self._partial_queue.queue.clear()

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
        """Real-time chunk bookkeeping only — must keep ticking on schedule
        no matter how far behind Whisper falls. This thread's only job is
        deciding utterance boundaries and handing finished audio off to
        _transcribe_worker() via the queues; it must never itself call
        _transcribe(). It used to, inline, and that was silently losing
        entire utterances: this loop only drains the audio ring buffer
        (RollingAudioBuffer, capacity BUFFER_SECONDS=30s) once per tick, so
        any tick delayed longer than that by a slow blocking transcribe()
        call meant read_since() came back having already lost whatever the
        ring buffer overwrote in the meantime — a pastor's scripture
        citation included, with no error, warning, or trace of it having
        been said at all."""
        assert self._capture is not None
        buf = self._capture.buffer

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

            if should_commit:
                audio = np.concatenate(utterance_chunks)
                self._final_queue.put((audio, utterance_started_at or time.time()))
            elif has_utterance:
                seconds_since_partial += chunk_seconds
                if seconds_since_partial >= PARTIAL_REFRESH_SECONDS:
                    audio = _tail_audio(utterance_chunks, PARTIAL_WINDOW_SECONDS)
                    # Latest-wins: clear out a still-pending stale partial
                    # (the worker hasn't gotten to it yet, likely because
                    # it's busy on a slow final) rather than let partials
                    # queue up behind each other — a delayed live-preview
                    # line has no value once a fresher one exists.
                    try:
                        self._partial_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._partial_queue.put_nowait((audio, utterance_started_at or time.time()))
                    except queue.Full:
                        pass
                    seconds_since_partial = 0.0

            if should_commit:
                utterance_chunks = []
                utterance_started_at = None
                silence_seconds = 0.0
                seconds_since_partial = 0.0

    def _transcribe_worker(self) -> None:
        """Runs the actual (slow, possibly minutes-behind) Whisper calls,
        off the real-time tick thread. Finals are drained first and never
        dropped — completeness there is what reference detection depends
        on; a partial is only picked up when no final is waiting, since a
        final always supersedes it anyway."""
        log = logging.getLogger("bible-transcriber")
        while not self._stop_event.is_set():
            try:
                audio, started_at = self._final_queue.get(timeout=0.2)
                is_final = True
            except queue.Empty:
                try:
                    audio, started_at = self._partial_queue.get_nowait()
                    is_final = False
                except queue.Empty:
                    continue

            try:
                text = self._transcribe(audio)
            except Exception:
                # A single bad chunk shouldn't take down the whole live loop —
                # log it and keep listening rather than silently going deaf.
                log.exception("Transcription of current utterance failed — discarding it")
                continue

            if text:
                self._on_segment(
                    TranscriptSegment(
                        text=text,
                        is_final=is_final,
                        started_at=started_at,
                        updated_at=time.time(),
                    )
                )
