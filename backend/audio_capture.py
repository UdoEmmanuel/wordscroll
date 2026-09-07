"""
Milestone 1: audio input device listing and a continuous rolling capture buffer.

Captured audio is kept as float32 mono samples at SAMPLE_RATE in a fixed-length
ring buffer. The transcription engine reads snapshots of the buffer; it never
blocks or interferes with the capture callback, which must stay fast and
allocation-free to avoid audio glitches.
"""
import logging
import threading

import numpy as np
import sounddevice as sd
from scipy.signal import firwin, lfilter, lfilter_zi

SAMPLE_RATE = 16000  # required input rate for whisper
CHANNELS = 1
BUFFER_SECONDS = 30  # how much rolling audio history we keep

logger = logging.getLogger("bible-transcriber")


class _StreamingResampler:
    """Anti-aliased, cross-chunk-stateful sample-rate converter.

    Used whenever a device rejects Whisper's required 16kHz and gets opened
    at its own native rate instead (see AudioCapture.start()) — routine for
    Windows "Microphone Array" devices, which is exactly the case a plain
    linear-interpolation resample (the previous approach here) handles
    badly: interpolating straight from e.g. 48kHz to 16kHz with no
    low-pass filtering first lets everything above the new 8kHz Nyquist
    fold back (alias) into the audible band as noise once decimated,
    quietly corrupting the very audio Whisper transcribes — not a subtle
    quality nicety, a direct hit to word accuracy. A low-pass FIR filter
    ahead of decimation, with its state carried from one audio callback to
    the next via scipy's lfilter(..., zi=...), removes that content first
    instead of letting it alias.
    """

    def __init__(self, orig_rate: int, target_rate: int, numtaps: int = 63):
        self.orig_rate = orig_rate
        self.target_rate = target_rate
        self._filter_b = None
        self._zi = None
        self._integer_factor: int | None = None
        self._sample_index = 0  # count of filtered samples seen so far, for exact-ratio decimation phase
        if orig_rate == target_rate:
            return
        nyquist = orig_rate / 2.0
        # A bit below the target's own Nyquist so the filter's transition
        # band (it isn't a brick wall) doesn't itself leak aliasing back in.
        cutoff = min(target_rate / 2.0 * 0.9, nyquist * 0.95)
        self._filter_b = firwin(numtaps, cutoff / nyquist)
        self._zi = lfilter_zi(self._filter_b, [1.0]) * 0.0
        if orig_rate % target_rate == 0:
            self._integer_factor = orig_rate // target_rate

    def process(self, samples: np.ndarray) -> np.ndarray:
        if self._filter_b is None or len(samples) == 0:
            return samples
        filtered, self._zi = lfilter(self._filter_b, [1.0], samples, zi=self._zi)
        filtered = filtered.astype(np.float32)

        if self._integer_factor is not None:
            # Exact ratio (e.g. 48000/16000 = 3) — decimate precisely rather
            # than resorting to interpolation at all. `start` picks up
            # exactly where the previous chunk's decimation left off, so the
            # output stays in phase across chunk boundaries instead of
            # resetting every callback.
            factor = self._integer_factor
            start = (-self._sample_index) % factor
            out = filtered[start::factor]
            self._sample_index += len(filtered)
            return out

        duration = len(filtered) / self.orig_rate
        target_n = max(1, round(duration * self.target_rate))
        orig_x = np.linspace(0.0, duration, num=len(filtered), endpoint=False)
        target_x = np.linspace(0.0, duration, num=target_n, endpoint=False)
        return np.interp(target_x, orig_x, filtered).astype(np.float32)


_VIRTUAL_DEVICE_NAMES = {"Microsoft Sound Mapper - Input", "Primary Sound Capture Driver"}
# Windows' preferred order for the *same* physical device when it's exposed
# through more than one host API — lower is preferred.
_HOSTAPI_PRIORITY = {"Windows WASAPI": 0, "Windows DirectSound": 1, "MME": 2, "Windows WDM-KS": 3}


def _is_junk_device_name(name: str) -> bool:
    """Filters out virtual/meta entries and WDM-KS raw-path stubs by name —
    NOT by host API. An earlier version of this function restricted the
    whole list to WASAPI-only, which also silently dropped a real,
    newly-plugged device that Windows only exposed via another API — too
    aggressive. Name-based junk filtering doesn't have that failure mode."""
    stripped = name.strip()
    if stripped in _VIRTUAL_DEVICE_NAMES:
        return True
    if stripped.endswith("()"):  # unnamed WDM-KS stubs, e.g. "Microphone Array 1 ()"
        return True
    if stripped.upper().startswith("MIDI"):
        return True
    if "PC Speaker" in stripped:  # outputs Windows misreports as inputs on WDM-KS
        return True
    return False


def refresh_device_list() -> None:
    """Forces PortAudio to re-enumerate devices from the OS.

    PortAudio caches its device list once per-process at init time and does
    NOT hot-refresh — sd.query_devices() alone keeps returning that same
    stale snapshot for the life of the process, so a jack plugged in (or
    unplugged) after the backend started never shows up (or never goes
    away) no matter how often /devices is polled. Pa_Terminate + Pa_Init
    (wrapped here as sounddevice's private _terminate()/_initialize()) is
    the standard, widely-used workaround for this exact PortAudio
    limitation — there's no public API for "just re-scan".

    Callers MUST NOT call this while a stream is open — tearing down and
    reinitializing PortAudio out from under an active InputStream would
    disrupt or crash that capture. main.py's /devices endpoint only calls
    this when nothing is currently capturing."""
    sd._terminate()
    sd._initialize()


def list_input_devices() -> list[dict]:
    """Windows exposes every physical device once per audio host API (MME,
    DirectSound, WASAPI, WDM-KS) — one real device can appear 3-4 times.
    De-duplicated here by device *name*, preferring the most modern API that
    exposes it (WASAPI > DirectSound > MME > WDM-KS) — but every host API is
    still searched, so a device only visible through a less-preferred API
    (e.g. some pro-audio/line-in interfaces, or a device plugged in after
    WASAPI last refreshed its own list) still shows up rather than being
    silently dropped. Separately, `_is_junk_device_name` drops virtual/meta
    entries and WDM-KS raw-path stubs by name, not by which API they came
    from. Devices that list here but fail to actually open (state that
    changes at any moment — unplugged, disabled, exclusively locked by
    another app — nothing this function can predict) surface a clear error
    from `/start` when selected instead."""
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    default_name = devices[sd.default.device[0]]["name"]

    best_by_name: dict[str, tuple[int, int, dict]] = {}  # name -> (priority, index, dev)
    for index, dev in enumerate(devices):
        if dev["max_input_channels"] <= 0:
            continue
        if _is_junk_device_name(dev["name"]):
            continue
        api_name = hostapis[dev["hostapi"]]["name"]
        priority = _HOSTAPI_PRIORITY.get(api_name, 99)
        existing = best_by_name.get(dev["name"])
        if existing is None or priority < existing[0]:
            best_by_name[dev["name"]] = (priority, index, dev)

    results = [
        {
            "index": index,
            "name": dev["name"],
            "default_samplerate": dev["default_samplerate"],
            "is_default": dev["name"] == default_name,
        }
        for _priority, index, dev in best_by_name.values()
    ]
    results.sort(key=lambda d: d["index"])
    return results


class RollingAudioBuffer:
    """Thread-safe fixed-size ring buffer of mono float32 audio samples."""

    def __init__(self, seconds: int = BUFFER_SECONDS, sample_rate: int = SAMPLE_RATE):
        self._capacity = seconds * sample_rate
        self._buffer = np.zeros(self._capacity, dtype=np.float32)
        self._write_pos = 0
        self._filled = 0
        self._total_written = 0  # monotonic logical sample count, never wraps
        self._lock = threading.Lock()
        self.sample_rate = sample_rate

    @property
    def total_written(self) -> int:
        with self._lock:
            return self._total_written

    def write(self, samples: np.ndarray) -> None:
        n = len(samples)
        if n == 0:
            return
        with self._lock:
            if n >= self._capacity:
                self._buffer[:] = samples[-self._capacity :]
                self._write_pos = 0
                self._filled = self._capacity
                self._total_written += n
                return
            end = self._write_pos + n
            if end <= self._capacity:
                self._buffer[self._write_pos : end] = samples
            else:
                first_len = self._capacity - self._write_pos
                self._buffer[self._write_pos :] = samples[:first_len]
                self._buffer[: end - self._capacity] = samples[first_len:]
            self._write_pos = end % self._capacity
            self._filled = min(self._capacity, self._filled + n)
            self._total_written += n

    def _read_physical(self, start: int, n: int) -> np.ndarray:
        if n == 0:
            return np.zeros(0, dtype=np.float32)
        if start + n <= self._capacity:
            return self._buffer[start : start + n].copy()
        first_len = self._capacity - start
        return np.concatenate((self._buffer[start:], self._buffer[: n - first_len]))

    def read_last(self, seconds: float) -> np.ndarray:
        """Return up to the last `seconds` of audio, oldest-first."""
        with self._lock:
            n = min(self._filled, int(seconds * self.sample_rate))
            if n == 0:
                return np.zeros(0, dtype=np.float32)
            start = (self._write_pos - n) % self._capacity
            return self._read_physical(start, n)

    def read_since(self, last_pos: int) -> tuple[np.ndarray, int]:
        """
        Return audio written since logical position `last_pos`, along with
        the new logical position to pass on the next call. If the caller
        fell behind and some of that audio was already overwritten, the
        gap is silently dropped (returns only what's still in the buffer).
        """
        with self._lock:
            available = self._total_written - last_pos
            if available <= 0:
                return np.zeros(0, dtype=np.float32), self._total_written
            available = min(available, self._filled)
            start_logical = self._total_written - available
            start = start_logical % self._capacity
            audio = self._read_physical(start, available)
            return audio, self._total_written


class AudioCapture:
    """Owns the sounddevice InputStream and feeds a RollingAudioBuffer."""

    def __init__(self, device_index: int, buffer: RollingAudioBuffer):
        self.device_index = device_index
        self.buffer = buffer
        self._stream: sd.InputStream | None = None
        self._capture_rate = buffer.sample_rate
        self._resampler: _StreamingResampler | None = None
        self.level = 0.0  # latest RMS of captured audio, 0..1ish; CPython attr assignment is atomic

    def _callback(self, indata, frames, time_info, status):
        # Runs on the audio thread — keep this cheap. Must never let an
        # exception escape: sounddevice treats an uncaught exception here as
        # a signal to silently abort the whole PortAudio stream, and nothing
        # else in the process gets notified — `is_running` used to just
        # check `self._stream is not None`, which stayed true forever after
        # that abort, so the app kept reporting "capturing" with a dead mic.
        # One bad chunk (a driver glitch, a momentary buffer hiccup) should
        # cost us that chunk, not the whole live session.
        try:
            if status:
                # Was previously discarded entirely — this is PortAudio's own
                # diagnosis of what's going wrong (input overflow/underflow),
                # and the one thing that could actually explain *why* a
                # stream keeps dying on a particular device instead of just
                # that it did.
                logger.warning("Audio callback status flags: %s", status)
            mono = indata[:, 0] if indata.ndim > 1 else indata
            mono = mono.astype(np.float32, copy=False)
            if self._resampler is not None:
                mono = self._resampler.process(mono)
            self.buffer.write(mono)
            self.level = float(np.sqrt(np.mean(np.square(mono)))) if len(mono) else 0.0
        except Exception:
            logger.exception("Audio callback error — dropping this chunk, stream stays open")

    def _open_stream(self, samplerate: int) -> None:
        self._stream = sd.InputStream(
            device=self.device_index,
            channels=CHANNELS,
            samplerate=samplerate,
            dtype="float32",
            # "Smart"/array microphones with onboard noise suppression or
            # beamforming (Windows' "Microphone Array" devices in
            # particular) are known to glitch under PortAudio/WASAPI's
            # default low-latency buffer sizing — that's the most likely
            # explanation for repeated silent stream deaths specifically on
            # this class of device. Requesting the host API's high-latency
            # buffer trades a bit of extra delay (irrelevant here — we
            # already batch audio into multi-second utterances) for a much
            # larger, more forgiving buffer.
            latency="high",
            callback=self._callback,
        )
        self._stream.start()
        self._capture_rate = samplerate
        self._resampler = (
            _StreamingResampler(samplerate, self.buffer.sample_rate)
            if samplerate != self.buffer.sample_rate
            else None
        )

    def start(self) -> None:
        if self.is_running:
            return
        if self._stream is not None:
            # A leftover from a stream PortAudio aborted on its own (device
            # unplugged, driver error, WASAPI hiccup) rather than one we
            # closed via stop() — self._stream stays non-None in that case,
            # so without this the old "if self._stream is not None: return"
            # check would make every recovery attempt a silent no-op.
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        forced_rate_error: Exception | None = None
        try:
            self._open_stream(self.buffer.sample_rate)
            return
        except Exception as exc:
            # Some line-in/pro-audio interfaces (e.g. a mixing console fed
            # through a 3.5mm jack or USB audio interface) reject a forced
            # 16kHz open even though the device works fine at its own native
            # rate — retry there and resample in software rather than
            # failing outright.
            #
            # Assigned to a second name here rather than reused straight from
            # `except ... as forced_rate_error`, because Python implicitly
            # deletes an `as`-bound exception name at the end of its except
            # block — every `raise forced_rate_error` below (reached once
            # that block has already exited) would otherwise fail with
            # "cannot access local variable 'forced_rate_error'", masking
            # the real device-open error behind a scoping bug instead of
            # reporting it to the operator.
            forced_rate_error = exc

        try:
            device_info = sd.query_devices(self.device_index)
            native_rate = int(round(device_info["default_samplerate"]))
        except Exception:
            raise forced_rate_error

        if native_rate == self.buffer.sample_rate:
            raise forced_rate_error  # native rate is the same one that just failed — no point retrying

        try:
            self._open_stream(native_rate)
            logger.info(
                "Device %s rejected %dHz; opened at its native %dHz instead and resampling in software",
                self.device_index, self.buffer.sample_rate, native_rate,
            )
        except Exception:
            raise forced_rate_error  # report the original error, not the fallback's — more useful to the operator

    def stop(self) -> None:
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None

    @property
    def is_running(self) -> bool:
        # `.active` reflects PortAudio's real state — `self._stream is not
        # None` alone doesn't, since a stream PortAudio aborted on its own
        # leaves the Stream object in place with nothing flowing through it.
        return self._stream is not None and self._stream.active
