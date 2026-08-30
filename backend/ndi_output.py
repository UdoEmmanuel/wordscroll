"""
Milestone 3: publishes the current display frame as a live NDI video source
with alpha (FR-9.1). Runs its own background thread pushing frames at a
steady rate — NDI receivers expect a continuous stream, not just on-change
pushes.

Gracefully degrades: if the `ndi-python` package or its bundled NDI runtime
fails to load (e.g. blocked by a locked-down machine), `NdiOutput.available`
is False and the rest of the app keeps working via the HTML overlay alone.
"""
import logging
import threading
import time

import numpy as np

from display_renderer import FRAME_HEIGHT, FRAME_WIDTH, render_blank_frame

logger = logging.getLogger("bible-transcriber")

FPS = 30
SOURCE_NAME = "WordScroll"

try:
    import NDIlib as ndi
    _NDI_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover — depends on machine's NDI runtime
    ndi = None
    _NDI_IMPORT_ERROR = exc


class NdiOutput:
    def __init__(self):
        self.available = False
        self.error: str | None = None
        self._sender = None
        self._frame = render_blank_frame()
        self._frame_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        if ndi is None:
            self.error = f"ndi-python not usable: {_NDI_IMPORT_ERROR}"
            logger.warning(self.error)
            return

        try:
            if not ndi.initialize():
                raise RuntimeError("NDIlib.initialize() returned False")
            send_settings = ndi.SendCreate()
            send_settings.ndi_name = SOURCE_NAME
            self._sender = ndi.send_create(send_settings)
            if self._sender is None:
                raise RuntimeError("NDIlib.send_create() returned None")
            self.available = True
            logger.info('NDI source "%s" created', SOURCE_NAME)
        except Exception as exc:
            self.error = f"Failed to start NDI sender: {exc}"
            logger.warning(self.error)

    def set_frame(self, frame: np.ndarray) -> None:
        with self._frame_lock:
            self._frame = frame

    def start(self) -> None:
        if not self.available or self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None
        if self._sender is not None:
            ndi.send_destroy(self._sender)
            self._sender = None
        if ndi is not None:
            ndi.destroy()
        self.available = False

    def _run(self) -> None:
        interval = 1.0 / FPS
        video_frame = ndi.VideoFrameV2()
        video_frame.xres = FRAME_WIDTH
        video_frame.yres = FRAME_HEIGHT
        video_frame.FourCC = ndi.FOURCC_VIDEO_TYPE_RGBA
        video_frame.frame_rate_N = FPS
        video_frame.frame_rate_D = 1

        while not self._stop_event.is_set():
            start = time.time()
            with self._frame_lock:
                frame = self._frame
            video_frame.data = frame
            try:
                ndi.send_send_video_v2(self._sender, video_frame)
            except Exception:
                logger.exception("NDI frame send failed — stopping NDI output")
                break
            elapsed = time.time() - start
            time.sleep(max(0.0, interval - elapsed))
