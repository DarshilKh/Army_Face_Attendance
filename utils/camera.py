"""
Camera Utility - Network Camera with System Webcam Fallback
कैमरा उपयोगिता / Camera Utility

Priority:
  1. Network camera (IP camera) — preferred
  2. System webcam (fallback if network camera fails)

All camera selection decisions and failures are logged.
"""

import cv2
import numpy as np
import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from utils.logger import app_logger
from config import Config
import time
import threading


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
        # Force TCP transport for RTSP — UDP drops packets under any network
        # load and produces stuttery/torn frames.  Must be set BEFORE opening.
        import os
        os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'
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


class CameraManager:
    """
    Manages camera sources with network camera priority and system webcam fallback.
    Logs all camera source decisions and failure reasons.
    """

    def __init__(self):
        self._network_cam_available = None  # None = not tested yet
        self._last_network_check = 0
        self._network_check_interval = 30  # Re-check network cam every 30 seconds after failure
        self._active_source = None  # 'network' or 'system'
        self._rtsp_reader = None  # RTSPStreamReader instance (background thread)

    def _test_network_camera(self):
        """
        Test if the network camera is reachable and responding.
        Returns True if camera is available, False otherwise.
        Logs the reason for any failure.
        """
        if not Config.CAMERA_URL:
            app_logger.info("📷 Network camera: Not configured (CAMERA_URL is empty)")
            return False

        camera_url = Config.CAMERA_URL.rstrip('/')

        # RTSP URLs can't be probed via `requests` (HTTP-only lib).  Skip HTTP
        # snapshot probing entirely and jump straight to OpenCV/FFMPEG.
        if camera_url.lower().startswith('rtsp://'):
            app_logger.info("📷 Detected RTSP URL — skipping HTTP snapshot probing")
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
        if Config.CAMERA_USERNAME and Config.CAMERA_PASSWORD:
            auth_basic  = HTTPBasicAuth(Config.CAMERA_USERNAME, Config.CAMERA_PASSWORD)
            auth_digest = HTTPDigestAuth(Config.CAMERA_USERNAME, Config.CAMERA_PASSWORD)

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
                        app_logger.info(f"✅ Network camera available: {Config.CAMERA_URL}")
                        app_logger.info(f"   Endpoint: {url}")
                        app_logger.info(f"   Auth type: {auth_type}")
                        app_logger.info(f"   Content-Type: {content_type}")
                        self._snapshot_url = url
                        self._auth_type    = auth_type
                        self._auth         = auth
                        return True
                    elif response.status_code == 401:
                        app_logger.warning(
                            f"🔐 Network camera auth failed ({auth_type}): {url} — HTTP 401 Unauthorized"
                        )
                    elif response.status_code != 200:
                        app_logger.debug(
                            f"   Network camera endpoint not found: {url} — HTTP {response.status_code}"
                        )
                except requests.exceptions.ConnectionError as e:
                    app_logger.warning(
                        f"❌ Network camera connection failed: {Config.CAMERA_URL} — {e}"
                    )
                    return False
                except requests.exceptions.Timeout:
                    app_logger.warning(
                        f"❌ Network camera timeout: {url} — Camera did not respond within 5 seconds"
                    )
                    return False
                except requests.exceptions.RequestException as e:
                    app_logger.warning(
                        f"❌ Network camera request error: {url} — {type(e).__name__}: {e}"
                    )

        # OpenCV VideoCapture path (RTSP/MJPEG) — this is where RTSP URLs land
        try:
            app_logger.info(f"   Trying OpenCV VideoCapture for network camera: {Config.CAMERA_URL}")
            cam_source = Config.get_camera_source()
            source_url = cam_source if isinstance(cam_source, str) else Config.CAMERA_URL
            try:
                # 5s open + read timeout — without this, an unreachable camera
                # can hang here effectively indefinitely (OpenCV 4.5.4+ needed
                # for this constructor form; falls back below on older builds).
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
                    app_logger.info(f"✅ Network camera available via OpenCV stream: {Config.CAMERA_URL}")
                    self._snapshot_url = None
                    self._auth_type    = "OpenCV"
                    self._auth         = None
                    return True
                else:
                    app_logger.warning(
                        f"❌ Network camera: OpenCV connected but failed to read frame from {Config.CAMERA_URL}"
                    )
            else:
                app_logger.warning(f"❌ Network camera: OpenCV could not open stream at {Config.CAMERA_URL}")
            cap.release()
        except Exception as e:
            app_logger.warning(f"❌ Network camera OpenCV error: {type(e).__name__}: {e}")

        app_logger.warning(
            f"❌ Network camera NOT available: {Config.CAMERA_URL} — All connection methods failed"
        )
        return False

    def get_camera_status(self):
        now = time.time()

        if self._network_cam_available is None or \
           (not self._network_cam_available and (now - self._last_network_check) > self._network_check_interval):
            self._last_network_check = now
            self._network_cam_available = self._test_network_camera()

            if self._network_cam_available:
                self._active_source = 'network'
                app_logger.info("🎥 CAMERA SOURCE: Network camera (PRIORITIZED)")
                app_logger.info(f"   URL: {Config.CAMERA_URL}")
            else:
                self._active_source = 'system'
                app_logger.info("🎥 CAMERA SOURCE: System webcam (FALLBACK)")
                app_logger.info(f"   Reason: Network camera at {Config.CAMERA_URL} is not available")
                app_logger.info(f"   Using system camera index: {Config.DEFAULT_CAMERA_INDEX}")

        return {
            'source':              self._active_source,
            'network_available':   self._network_cam_available,
            'camera_url':          Config.CAMERA_URL if self._active_source == 'network' else None,
            'use_browser_webcam':  self._active_source == 'system',
        }

    def capture_frame(self):
        status = self.get_camera_status()

        if status['source'] == 'network':
            success, frame = self._capture_from_network()
            if success:
                return True, frame, 'network'
            else:
                app_logger.warning("⚠️ Network camera failed during capture, falling back to system webcam")
                self._network_cam_available = False
                self._active_source = 'system'

                # Release the background reader when abandoning the network camera
                if self._rtsp_reader is not None:
                    self._rtsp_reader.release()
                    self._rtsp_reader = None

        success, frame = self._capture_from_system()
        if success:
            return True, frame, 'system'

        app_logger.error("❌ All camera sources failed — no frame captured")
        return False, None, None

    def _capture_from_network(self):
        """Capture a frame from the network camera."""
        try:
            if hasattr(self, '_snapshot_url') and self._snapshot_url:
                # HTTP snapshot camera — no buffering issues here
                response = requests.get(self._snapshot_url, auth=self._auth, timeout=5)
                if response.status_code == 200:
                    img_array = np.frombuffer(response.content, dtype=np.uint8)
                    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if frame is not None:
                        return True, frame
                    app_logger.warning("❌ Network camera: Failed to decode snapshot image")
                else:
                    app_logger.warning(f"❌ Network camera snapshot HTTP {response.status_code}")
            else:
                # ── Bug fix ──────────────────────────────────────────────────
                # Previous approaches (persistent cv2.VideoCapture + CAP_PROP_
                # BUFFERSIZE=1 + grab-twice-then-retrieve) all failed to keep
                # up because our detection loop consumes at ~0.66 FPS while the
                # RTSP camera pushes at ~25–30 FPS.  The FFMPEG buffer fills
                # up between calls faster than we can drain it, so every read
                # returns a stale queued frame — producing the "confidence
                # slowly inches up while the picture looks frozen" symptom.
                #
                # Real fix: a background thread that drains the stream at the
                # camera's native FPS and holds only the newest frame.  When
                # we ask for a frame, we get whatever's current *right now* —
                # no queue drain, no decode wait, no lag.
                #
                # Startup cost is one-time (spawning the thread + first frame
                # arriving ~30-100ms later).  Steady-state cost per capture is
                # a single lock + memory copy.
                # ────────────────────────────────────────────────────────────
                if self._rtsp_reader is None or not self._rtsp_reader.is_alive():
                    if self._rtsp_reader is not None:
                        # Previous reader died — clean it up before replacing
                        self._rtsp_reader.release()
                    cam_source = Config.get_camera_source()
                    url = cam_source if isinstance(cam_source, str) else Config.CAMERA_URL
                    self._rtsp_reader = RTSPStreamReader(url)
                    # Give the thread a moment to grab its first frame
                    time.sleep(0.3)

                ret, frame = self._rtsp_reader.read()
                if ret and frame is not None:
                    return True, frame
                app_logger.warning("❌ Network camera: No frame available yet from background reader")

        except requests.exceptions.ConnectionError:
            app_logger.warning(f"❌ Network camera lost connection: {Config.CAMERA_URL}")
        except requests.exceptions.Timeout:
            app_logger.warning(f"❌ Network camera timeout during capture: {Config.CAMERA_URL}")
        except Exception as e:
            app_logger.warning(f"❌ Network camera capture error: {type(e).__name__}: {e}")
            if self._rtsp_reader is not None:
                self._rtsp_reader.release()
                self._rtsp_reader = None

        return False, None

    def _capture_from_system(self):
        """Capture a frame from the system webcam (kept open across calls)."""
        try:
            if getattr(self, '_system_cap', None) is None:
                self._system_cap = cv2.VideoCapture(Config.DEFAULT_CAMERA_INDEX)
                # Apply resolution/FPS from Settings — cameras that don't
                # support the exact requested mode will silently fall back
                # to their closest native mode, which is standard OpenCV
                # behavior and not an error.
                self._system_cap.set(cv2.CAP_PROP_FRAME_WIDTH, Config.CAMERA_WIDTH)
                self._system_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.CAMERA_HEIGHT)
                self._system_cap.set(cv2.CAP_PROP_FPS, Config.CAMERA_FPS)

            if self._system_cap.isOpened():
                ret, frame = self._system_cap.read()
                if ret and frame is not None:
                    return True, frame
                else:
                    app_logger.warning("❌ System webcam: Failed to read frame, resetting camera")
                    self._system_cap.release()
                    self._system_cap = None
            else:
                app_logger.warning(
                    f"❌ System webcam: Could not open camera index {Config.DEFAULT_CAMERA_INDEX}"
                )
                self._system_cap.release()
                self._system_cap = None
        except Exception as e:
            app_logger.error(f"❌ System webcam error: {type(e).__name__}: {e}")
            if getattr(self, '_system_cap', None) is not None:
                self._system_cap.release()
                self._system_cap = None

        return False, None

    def get_snapshot_url(self):
        status = self.get_camera_status()
        if status['source'] == 'network':
            return '/api/camera/snapshot'
        return None

    def reset(self):
        """Force re-check of camera availability."""
        if getattr(self, '_system_cap', None) is not None:
            self._system_cap.release()
            self._system_cap = None
        if self._rtsp_reader is not None:
            self._rtsp_reader.release()
            self._rtsp_reader = None
        self._network_cam_available = None
        self._active_source = None
        app_logger.info("🔄 Camera manager reset — will re-check on next request")

    def __del__(self):
        """Cleanup resources on shutdown"""
        if getattr(self, '_system_cap', None) is not None:
            try:
                self._system_cap.release()
            except Exception:
                pass
        if getattr(self, '_rtsp_reader', None) is not None:
            try:
                self._rtsp_reader.release()
            except Exception:
                pass


# Singleton instance
camera_manager = CameraManager()