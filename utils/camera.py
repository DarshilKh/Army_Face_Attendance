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
        # Common snapshot endpoints for IP cameras
        snapshot_urls = [
            f"{camera_url}/snap.jpeg",
            f"{camera_url}/snapshot.jpg",
            f"{camera_url}/cgi-bin/snapshot.cgi",
            f"{camera_url}/image/jpeg.cgi",
            f"{camera_url}/jpg/image.jpg",
            f"{camera_url}/ISAPI/Streaming/channels/1/picture",
            f"{camera_url}/onvif-http/snapshot",
            camera_url,  # Try base URL last
        ]

        auth_basic = None
        auth_digest = None
        if Config.CAMERA_USERNAME and Config.CAMERA_PASSWORD:
            auth_basic = HTTPBasicAuth(Config.CAMERA_USERNAME, Config.CAMERA_PASSWORD)
            auth_digest = HTTPDigestAuth(Config.CAMERA_USERNAME, Config.CAMERA_PASSWORD)

        for url in snapshot_urls:
            # Try Basic Auth first, then Digest Auth
            for auth_type, auth in [("Basic", auth_basic), ("Digest", auth_digest), ("None", None)]:
                if auth is None and auth_type != "None":
                    continue
                try:
                    response = requests.get(url, auth=auth, timeout=5, stream=True)
                    content_type = response.headers.get('Content-Type', '')

                    if response.status_code == 200 and ('image' in content_type or 'multipart' in content_type or 'octet-stream' in content_type):
                        app_logger.info(f"✅ Network camera available: {Config.CAMERA_URL}")
                        app_logger.info(f"   Endpoint: {url}")
                        app_logger.info(f"   Auth type: {auth_type}")
                        app_logger.info(f"   Content-Type: {content_type}")
                        self._snapshot_url = url
                        self._auth_type = auth_type
                        self._auth = auth
                        return True
                    elif response.status_code == 401:
                        app_logger.warning(f"🔐 Network camera auth failed ({auth_type}): {url} — HTTP 401 Unauthorized")
                    elif response.status_code != 200:
                        app_logger.debug(f"   Network camera endpoint not found: {url} — HTTP {response.status_code}")
                except requests.exceptions.ConnectionError as e:
                    app_logger.warning(f"❌ Network camera connection failed: {Config.CAMERA_URL} — Connection refused/unreachable. Error: {e}")
                    return False  # No point trying other URLs if can't connect
                except requests.exceptions.Timeout:
                    app_logger.warning(f"❌ Network camera timeout: {url} — Camera did not respond within 5 seconds")
                    return False  # Network issue, don't try more
                except requests.exceptions.RequestException as e:
                    app_logger.warning(f"❌ Network camera request error: {url} — {type(e).__name__}: {e}")

        # Try MJPEG/RTSP via OpenCV as last resort
        try:
            app_logger.info(f"   Trying OpenCV VideoCapture for network camera: {Config.CAMERA_URL}")
            cam_source = Config.get_camera_source()
            cap = cv2.VideoCapture(cam_source if isinstance(cam_source, str) else Config.CAMERA_URL)
            if cap.isOpened():
                ret, frame = cap.read()
                cap.release()
                if ret and frame is not None:
                    app_logger.info(f"✅ Network camera available via OpenCV stream: {Config.CAMERA_URL}")
                    self._snapshot_url = None  # Use OpenCV for capture
                    self._auth_type = "OpenCV"
                    self._auth = None
                    return True
                else:
                    app_logger.warning(f"❌ Network camera: OpenCV connected but failed to read frame from {Config.CAMERA_URL}")
            else:
                app_logger.warning(f"❌ Network camera: OpenCV could not open stream at {Config.CAMERA_URL}")
            cap.release()
        except Exception as e:
            app_logger.warning(f"❌ Network camera OpenCV error: {type(e).__name__}: {e}")

        app_logger.warning(f"❌ Network camera NOT available: {Config.CAMERA_URL} — All connection methods failed")
        return False

    def get_camera_status(self):
        """
        Determine which camera to use. Network camera is prioritized.
        Returns dict with camera info and source type.
        """
        now = time.time()

        # Re-check network camera if it was previously unavailable and interval has passed
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
            'source': self._active_source,
            'network_available': self._network_cam_available,
            'camera_url': Config.CAMERA_URL if self._active_source == 'network' else None,
            'use_browser_webcam': self._active_source == 'system',
        }

    def capture_frame(self):
        """
        Capture a single frame from the active camera source.
        Tries network camera first, falls back to system webcam.
        Returns (success, frame, source) tuple.
        """
        status = self.get_camera_status()

        if status['source'] == 'network':
            success, frame = self._capture_from_network()
            if success:
                return True, frame, 'network'
            else:
                # Network camera failed mid-session, fallback
                app_logger.warning("⚠️ Network camera failed during capture, falling back to system webcam")
                self._network_cam_available = False
                self._active_source = 'system'

        # Fallback to system webcam
        success, frame = self._capture_from_system()
        if success:
            return True, frame, 'system'

        app_logger.error("❌ All camera sources failed — no frame captured")
        return False, None, None

    def _capture_from_network(self):
        """Capture a frame from the network camera."""
        try:
            if hasattr(self, '_snapshot_url') and self._snapshot_url:
                # Use HTTP snapshot
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
                # Use OpenCV stream
                cam_source = Config.get_camera_source()
                cap = cv2.VideoCapture(cam_source if isinstance(cam_source, str) else Config.CAMERA_URL)
                if cap.isOpened():
                    ret, frame = cap.read()
                    cap.release()
                    if ret and frame is not None:
                        return True, frame
                    app_logger.warning("❌ Network camera: OpenCV read failed")
                else:
                    app_logger.warning("❌ Network camera: OpenCV could not open stream")
                    cap.release()
        except requests.exceptions.ConnectionError:
            app_logger.warning(f"❌ Network camera lost connection: {Config.CAMERA_URL}")
        except requests.exceptions.Timeout:
            app_logger.warning(f"❌ Network camera timeout during capture: {Config.CAMERA_URL}")
        except Exception as e:
            app_logger.warning(f"❌ Network camera capture error: {type(e).__name__}: {e}")

        return False, None

    def _capture_from_system(self):
        """Capture a frame from the system webcam (Optimized to keep camera open)."""
        try:
            # Bug #14 fix: Keep camera open instead of re-initializing per frame
            if getattr(self, '_system_cap', None) is None:
                self._system_cap = cv2.VideoCapture(Config.DEFAULT_CAMERA_INDEX)
            
            if self._system_cap.isOpened():
                ret, frame = self._system_cap.read()
                if ret and frame is not None:
                    return True, frame
                else:
                    app_logger.warning("❌ System webcam: Failed to read frame, resetting camera")
                    self._system_cap.release()
                    self._system_cap = None
            else:
                app_logger.warning(f"❌ System webcam: Could not open camera index {Config.DEFAULT_CAMERA_INDEX}")
                self._system_cap.release()
                self._system_cap = None
        except Exception as e:
            app_logger.error(f"❌ System webcam error: {type(e).__name__}: {e}")
            if getattr(self, '_system_cap', None) is not None:
                self._system_cap.release()
                self._system_cap = None

        return False, None

    def get_snapshot_url(self):
        """
        Get the URL that the frontend can use to display the network camera feed.
        Returns None if network camera is not available (frontend should use getUserMedia).
        """
        status = self.get_camera_status()
        if status['source'] == 'network':
            # Return the proxy URL (served by our Flask app) to avoid exposing credentials
            return '/api/camera/snapshot'
        return None

    def reset(self):
        """Force re-check of camera availability."""
        if getattr(self, '_system_cap', None) is not None:
            self._system_cap.release()
            self._system_cap = None
        self._network_cam_available = None
        self._active_source = None
        app_logger.info("🔄 Camera manager reset — will re-check on next request")

    def __del__(self):
        """Cleanup resources on shutdown"""
        if getattr(self, '_system_cap', None) is not None:
            self._system_cap.release()


# Singleton instance
camera_manager = CameraManager()
