"""
Camera Registry - Multi-Camera Support (IP cameras)
कैमरा उपयोगिता / Camera Utility

Each entry-point site can register any number of IP cameras from Settings.
'webcam' type cameras are accessed directly by the browser via getUserMedia
and never touch this module — it only manages IP/RTSP camera sources, keyed
by their DB row id, so multiple cameras can be open concurrently.

All camera selection decisions and failures are logged.
"""

import cv2
import numpy as np
import os
import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from urllib.parse import urlparse, urlunparse, quote_plus
from dataclasses import dataclass
from utils.logger import app_logger
import time
import threading

# Process-wide FFMPEG options for every cv2.VideoCapture(..., cv2.CAP_FFMPEG)
# call in this module — set once at import time so it's guaranteed to be in
# effect before ANY capture is opened, including _test_camera()'s OpenCV
# fallback path (which previously relied on RTSPStreamReader having already
# run once to set this, an ordering gap for the very first Test-button click).
#
#   rtsp_transport;tcp — UDP drops packets under any network load and
#     produces stuttery/torn frames.
#   tls_verify;0 — some cameras (e.g. CP PLUS models with a hardened/secure
#     firmware posture) run RTSP over TLS (rtsps://) with a self-signed
#     certificate. This only takes effect when ffmpeg actually attempts a
#     TLS handshake, i.e. only for rtsps:// URLs — a plain rtsp:// camera
#     never touches this code path, so it's inert for them.
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp|tls_verify;0'


@dataclass
class CameraConfig:
    """Plain snapshot of a Camera DB row's fields needed to open a stream.
    Passed in by callers (routes/camera.py) so this module never has to
    touch the database or depend on an active Flask app/request context."""
    id: int
    url: str
    username: str = ''
    password: str = ''
    width: int = 1280
    height: int = 720
    fps: int = 15


# ═══════════════════════════════════════════════════════════════════════════
# RTSPStreamReader — background thread that continuously drains an RTSP
# stream at native FPS and exposes only the most-recent frame.
#
# Why this exists:
#   RTSP cameras push frames at their native FPS (usually 25–30 FPS).  If we
#   consume slower than that (our detection loop ticks every 1.5s = ~0.66 FPS),
#   the internal FFMPEG buffer fills up and every .read() returns a stale
#   queued frame.  CAP_PROP_BUFFERSIZE=1 is silently ignored on Windows, and
#   grab-and-discard only helps if you drain faster than the camera pushes —
#   which is impossible from a slow consumer.
#
# Solution:
#   Run a background thread that reads frames as fast as the camera produces
#   them, keeping only the latest one in a single-slot buffer.  When the
#   detection loop asks for a frame, it gets whatever is current *right now* —
#   never a stale queued frame, never a slow decode.
# ═══════════════════════════════════════════════════════════════════════════
class RTSPStreamReader:
    def __init__(self, url):
        self.url = url
        # OPENCV_FFMPEG_CAPTURE_OPTIONS is set once at module import (see top
        # of file) — no need to set it again here.
        try:
            self.cap = cv2.VideoCapture(
                url, cv2.CAP_FFMPEG,
                (cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
            )
        except TypeError:
            self.cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # honored by some backends
        self._latest_frame = None
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()
        app_logger.info(f"🎬 RTSP background reader started for {url}")

    def _reader_loop(self):
        """Continuously drain the stream, keeping only the latest frame."""
        consecutive_failures = 0
        while self._running:
            try:
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    with self._lock:
                        self._latest_frame = frame
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    # After 30 consecutive failures (~1s at 30fps), try reconnecting
                    if consecutive_failures >= 30:
                        app_logger.warning(
                            f"⚠️ RTSP reader: {consecutive_failures} consecutive read failures, reconnecting"
                        )
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                        time.sleep(0.5)
                        try:
                            self.cap = cv2.VideoCapture(
                                self.url, cv2.CAP_FFMPEG,
                                (cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
                            )
                        except TypeError:
                            self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        consecutive_failures = 0
            except Exception as e:
                app_logger.warning(f"⚠️ RTSP reader loop error: {type(e).__name__}: {e}")
                time.sleep(0.1)

    def read(self):
        """Return the most-recent frame captured by the background thread."""
        with self._lock:
            if self._latest_frame is None:
                return False, None
            # Return a copy so callers can modify freely without affecting future reads
            return True, self._latest_frame.copy()

    def is_alive(self):
        """Return True if the background reader is still running and producing frames."""
        return self._running and self._thread.is_alive()

    def release(self):
        """Stop the background thread and release the underlying VideoCapture."""
        self._running = False
        try:
            self._thread.join(timeout=2.0)
        except Exception:
            pass
        try:
            self.cap.release()
        except Exception:
            pass
        app_logger.info(f"🛑 RTSP background reader stopped for {self.url}")


class _CameraState:
    """Runtime state for one IP camera row — availability cache + the
    background RTSP reader (or HTTP snapshot endpoint) once discovered."""

    def __init__(self):
        self.network_available = None      # None = not tested yet
        self.last_check = 0
        self.check_interval = 30           # Re-check every 30s after failure
        self.rtsp_reader = None
        self.snapshot_url = None
        self.auth_type = None
        self.auth = None

    def release(self):
        if self.rtsp_reader is not None:
            self.rtsp_reader.release()
            self.rtsp_reader = None


def _build_auth_url(cfg: CameraConfig) -> str:
    """Build an authenticated URL if credentials are provided, matching the
    single-camera Config.get_camera_source() behavior this replaces."""
    if cfg.username and cfg.password:
        parsed = urlparse(cfg.url)
        return urlunparse((
            parsed.scheme,
            f"{quote_plus(cfg.username)}:{quote_plus(cfg.password)}@{parsed.hostname}" +
            (f":{parsed.port}" if parsed.port else ""),
            parsed.path, parsed.params, parsed.query, parsed.fragment
        ))
    return cfg.url


class CameraRegistry:
    """
    Manages any number of IP camera sources, keyed by their DB row id, so
    multiple entry-point cameras can be open and streaming concurrently.
    Logs all camera source decisions and failure reasons.
    """

    def __init__(self):
        self._states = {}
        self._lock = threading.Lock()

    def _state(self, camera_id) -> _CameraState:
        with self._lock:
            if camera_id not in self._states:
                self._states[camera_id] = _CameraState()
            return self._states[camera_id]

    def _test_camera(self, cfg: CameraConfig, state: _CameraState) -> bool:
        """Test if the IP camera is reachable and responding."""
        if not cfg.url:
            app_logger.info(f"📷 Camera {cfg.id}: Not configured (no URL)")
            return False

        camera_url = cfg.url.rstrip('/')

        if camera_url.lower().startswith(('rtsp://', 'rtsps://')):
            app_logger.info(f"📷 Camera {cfg.id}: Detected RTSP URL — skipping HTTP snapshot probing")
            snapshot_urls = []
        else:
            snapshot_urls = [
                f"{camera_url}/snap.jpeg",
                f"{camera_url}/snapshot.jpg",
                f"{camera_url}/cgi-bin/snapshot.cgi",
                f"{camera_url}/image/jpeg.cgi",
                f"{camera_url}/jpg/image.jpg",
                f"{camera_url}/ISAPI/Streaming/channels/1/picture",
                f"{camera_url}/onvif-http/snapshot",
                camera_url,
            ]

        auth_basic = None
        auth_digest = None
        if cfg.username and cfg.password:
            auth_basic = HTTPBasicAuth(cfg.username, cfg.password)
            auth_digest = HTTPDigestAuth(cfg.username, cfg.password)

        for url in snapshot_urls:
            for auth_type, auth in [("Basic", auth_basic), ("Digest", auth_digest), ("None", None)]:
                if auth is None and auth_type != "None":
                    continue
                try:
                    response = requests.get(url, auth=auth, timeout=5, stream=True)
                    content_type = response.headers.get('Content-Type', '')

                    if response.status_code == 200 and (
                        'image' in content_type
                        or 'multipart' in content_type
                        or 'octet-stream' in content_type
                    ):
                        app_logger.info(f"✅ Camera {cfg.id} available: {cfg.url}")
                        app_logger.info(f"   Endpoint: {url}")
                        app_logger.info(f"   Auth type: {auth_type}")
                        state.snapshot_url = url
                        state.auth_type = auth_type
                        state.auth = auth
                        return True
                    elif response.status_code == 401:
                        app_logger.warning(
                            f"🔐 Camera {cfg.id} auth failed ({auth_type}): {url} — HTTP 401 Unauthorized"
                        )
                    elif response.status_code != 200:
                        app_logger.debug(
                            f"   Camera {cfg.id} endpoint not found: {url} — HTTP {response.status_code}"
                        )
                except requests.exceptions.ConnectionError as e:
                    app_logger.warning(f"❌ Camera {cfg.id} connection failed: {cfg.url} — {e}")
                    return False
                except requests.exceptions.Timeout:
                    app_logger.warning(f"❌ Camera {cfg.id} timeout: {url} — no response within 5 seconds")
                    return False
                except requests.exceptions.RequestException as e:
                    app_logger.warning(f"❌ Camera {cfg.id} request error: {url} — {type(e).__name__}: {e}")

        # OpenCV VideoCapture path (RTSP/MJPEG)
        try:
            app_logger.info(f"   Camera {cfg.id}: Trying OpenCV VideoCapture: {cfg.url}")
            source_url = _build_auth_url(cfg)
            try:
                cap = cv2.VideoCapture(
                    source_url, cv2.CAP_FFMPEG,
                    (cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
                )
            except TypeError:
                cap = cv2.VideoCapture(source_url)
            if cap.isOpened():
                ret, frame = cap.read()
                cap.release()
                if ret and frame is not None:
                    app_logger.info(f"✅ Camera {cfg.id} available via OpenCV stream: {cfg.url}")
                    state.snapshot_url = None
                    state.auth_type = "OpenCV"
                    state.auth = None
                    return True
                else:
                    app_logger.warning(f"❌ Camera {cfg.id}: OpenCV connected but failed to read frame")
            else:
                app_logger.warning(f"❌ Camera {cfg.id}: OpenCV could not open stream")
                cap.release()
        except Exception as e:
            app_logger.warning(f"❌ Camera {cfg.id} OpenCV error: {type(e).__name__}: {e}")

        app_logger.warning(f"❌ Camera {cfg.id} NOT available: {cfg.url} — All connection methods failed")
        return False

    def get_status(self, cfg: CameraConfig) -> dict:
        state = self._state(cfg.id)
        now = time.time()

        if state.network_available is None or \
           (not state.network_available and (now - state.last_check) > state.check_interval):
            state.last_check = now
            state.network_available = self._test_camera(cfg, state)

        return {
            'id': cfg.id,
            'available': state.network_available,
        }

    def test(self, cfg: CameraConfig) -> dict:
        """Force an immediate re-check, bypassing the 30s failure-backoff cache.
        Used by the 'Test' button in Settings > Cameras."""
        state = self._state(cfg.id)
        state.network_available = None
        state.last_check = 0
        return self.get_status(cfg)

    def capture_frame(self, cfg: CameraConfig):
        """Returns (success, frame_ndarray_or_None)."""
        status = self.get_status(cfg)
        if not status['available']:
            return False, None

        state = self._state(cfg.id)
        try:
            if state.snapshot_url:
                response = requests.get(state.snapshot_url, auth=state.auth, timeout=5)
                if response.status_code == 200:
                    img_array = np.frombuffer(response.content, dtype=np.uint8)
                    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if frame is not None:
                        return True, frame
                    app_logger.warning(f"❌ Camera {cfg.id}: Failed to decode snapshot image")
                else:
                    app_logger.warning(f"❌ Camera {cfg.id} snapshot HTTP {response.status_code}")
            else:
                # Background thread drains the RTSP stream at native FPS and holds
                # only the newest frame — see RTSPStreamReader docstring for why.
                if state.rtsp_reader is None or not state.rtsp_reader.is_alive():
                    if state.rtsp_reader is not None:
                        state.rtsp_reader.release()
                    url = _build_auth_url(cfg)
                    state.rtsp_reader = RTSPStreamReader(url)
                    time.sleep(0.3)  # give the thread a moment to grab its first frame

                ret, frame = state.rtsp_reader.read()
                if ret and frame is not None:
                    return True, frame
                app_logger.warning(f"❌ Camera {cfg.id}: No frame available yet from background reader")

        except requests.exceptions.ConnectionError:
            app_logger.warning(f"❌ Camera {cfg.id} lost connection: {cfg.url}")
        except requests.exceptions.Timeout:
            app_logger.warning(f"❌ Camera {cfg.id} timeout during capture: {cfg.url}")
        except Exception as e:
            app_logger.warning(f"❌ Camera {cfg.id} capture error: {type(e).__name__}: {e}")
            state.release()

        return False, None

    def reset(self, camera_id):
        """Force re-check of one camera's availability (e.g. after editing it)."""
        with self._lock:
            state = self._states.pop(camera_id, None)
        if state:
            state.release()
        app_logger.info(f"🔄 Camera {camera_id} reset — will re-check on next request")

    def reset_all(self):
        with self._lock:
            ids = list(self._states.keys())
        for camera_id in ids:
            self.reset(camera_id)


# Singleton instance
camera_manager = CameraRegistry()
