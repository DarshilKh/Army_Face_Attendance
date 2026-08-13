"""
Camera API Routes - Network Camera Proxy & Status
Serves network camera frames to the frontend without exposing credentials.
"""

from flask import Blueprint, Response, jsonify
from flask_login import login_required
from utils.camera import camera_manager
from utils.logger import app_logger
from config import Config
import cv2
import time

camera_bp = Blueprint('camera', __name__, url_prefix='/api/camera')


@camera_bp.route('/status')
@login_required
def camera_status():
    """Get current camera status and source info"""
    status = camera_manager.get_camera_status()
    return jsonify(status)


@camera_bp.route('/snapshot')
@login_required
def camera_snapshot():
    """
    Get a single snapshot from the active camera (network or system).
    Returns JPEG image. Used by frontend as <img src="/api/camera/snapshot">.
    """
    success, frame, source = camera_manager.capture_frame()

    if success and frame is not None:
        # DEBUG: log the actual resolution we're receiving from the camera
        print(f"📐 Frame from '{source}': {frame.shape[1]}x{frame.shape[0]} (WxH)")

        # Encode frame as JPEG
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if ret:
            return Response(
                buffer.tobytes(),
                mimetype='image/jpeg',
                headers={
                    'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
                    'X-Camera-Source': source or 'unknown'
                }
            )

    return Response('Camera unavailable', status=503, mimetype='text/plain')


@camera_bp.route('/stream')
@login_required
def camera_stream():
    """
    MJPEG stream from the active camera.
    Used by frontend as <img src="/api/camera/stream">.
    Priority: network camera → system webcam.
    """
    def generate_frames():
        app_logger.info("🎥 MJPEG stream started")
        frame_count = 0
        error_count = 0
        max_errors = 10  # Stop after 10 consecutive errors

        while True:
            success, frame, source = camera_manager.capture_frame()

            if success and frame is not None:
                error_count = 0  # Reset error counter
                frame_count += 1

                # Log source periodically
                if frame_count == 1 or frame_count % 100 == 0:
                    app_logger.info(f"🎥 MJPEG stream: {frame_count} frames served from {source} camera")

                # Encode as JPEG
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' +
                           buffer.tobytes() +
                           b'\r\n')
            else:
                error_count += 1
                app_logger.warning(f"⚠️ MJPEG stream: Frame capture failed (error {error_count}/{max_errors})")
                if error_count >= max_errors:
                    app_logger.error("❌ MJPEG stream: Too many consecutive errors, stopping stream")
                    break

            # Control frame rate from Settings (falls back to a sane default
            # if CAMERA_FPS is ever misconfigured as 0 or negative)
            time.sleep(1.0 / max(Config.CAMERA_FPS, 1))

        app_logger.info(f"🎥 MJPEG stream ended after {frame_count} frames")

    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0'}
    )


@camera_bp.route('/reset', methods=['POST'])
@login_required
def reset_camera():
    """Force re-check camera availability"""
    camera_manager.reset()
    status = camera_manager.get_camera_status()
    app_logger.info(f"🔄 Camera reset requested — new source: {status['source']}")
    return jsonify({
        'success': True,
        'message': f"Camera reset. Active source: {status['source']}",
        **status
    })