"""
Camera API Routes - Multi-Camera CRUD + Network Camera Proxy & Status
Serves IP camera frames to the frontend without exposing credentials.
'webcam' type cameras are handled entirely client-side (getUserMedia) and
never reach this module.
"""

from flask import Blueprint, Response, jsonify, request
from flask_login import login_required, current_user
from models import db
from models.database import Camera
from utils.camera import camera_manager, CameraConfig
from utils.logger import app_logger
import cv2
import time

camera_bp = Blueprint('camera', __name__, url_prefix='/api')


def _to_config(camera: Camera) -> CameraConfig:
    return CameraConfig(
        id=camera.id,
        url=camera.url or '',
        username=camera.username or '',
        password=camera.password or '',
        width=camera.width or 1280,
        height=camera.height or 720,
        fps=camera.fps or 15,
    )


# ============================================
# CAMERA CRUD (Settings > Cameras)
# ============================================

@camera_bp.route('/cameras')
@login_required
def list_cameras():
    """List all cameras — used to populate the picker on Mark Attendance/Registration."""
    active_only = request.args.get('active_only', '1') != '0'
    query = Camera.query
    if active_only:
        query = query.filter_by(is_active=True)
    cameras = query.order_by(Camera.id.asc()).all()
    return jsonify({'success': True, 'cameras': [c.to_dict() for c in cameras]})


@camera_bp.route('/cameras/<int:camera_id>')
@login_required
def get_camera(camera_id):
    """Full camera details including credentials — admin only, used to prefill the edit modal."""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Admin only'}), 403

    camera = Camera.query.get_or_404(camera_id)
    return jsonify({'success': True, 'camera': camera.to_dict(include_credentials=True)})


@camera_bp.route('/cameras', methods=['POST'])
@login_required
def create_camera():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Admin only'}), 403

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    camera_type = data.get('camera_type', 'webcam')

    if not name:
        return jsonify({'success': False, 'message': 'Camera name is required'}), 400
    if camera_type not in ('webcam', 'ip'):
        return jsonify({'success': False, 'message': 'Invalid camera type'}), 400
    if camera_type == 'ip' and not (data.get('url') or '').strip():
        return jsonify({'success': False, 'message': 'URL is required for an IP camera'}), 400

    camera = Camera(
        name=name,
        location=(data.get('location') or '').strip(),
        camera_type=camera_type,
        url=(data.get('url') or '').strip() if camera_type == 'ip' else None,
        username=(data.get('username') or '').strip() if camera_type == 'ip' else None,
        password=(data.get('password') or '').strip() if camera_type == 'ip' else None,
        width=int(data.get('width') or 1280),
        height=int(data.get('height') or 720),
        fps=int(data.get('fps') or 15),
        is_active=bool(data.get('is_active', True)),
    )
    db.session.add(camera)
    db.session.commit()

    app_logger.info(f"Camera added by {current_user.username}: {camera.name} ({camera.camera_type})")
    return jsonify({'success': True, 'message': 'Camera added', 'camera': camera.to_dict()}), 201


@camera_bp.route('/cameras/<int:camera_id>', methods=['PUT'])
@login_required
def update_camera(camera_id):
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Admin only'}), 403

    camera = Camera.query.get_or_404(camera_id)
    data = request.get_json() or {}

    name = (data.get('name') or '').strip()
    camera_type = data.get('camera_type', camera.camera_type)

    if not name:
        return jsonify({'success': False, 'message': 'Camera name is required'}), 400
    if camera_type not in ('webcam', 'ip'):
        return jsonify({'success': False, 'message': 'Invalid camera type'}), 400
    if camera_type == 'ip' and not (data.get('url') or camera.url or '').strip():
        return jsonify({'success': False, 'message': 'URL is required for an IP camera'}), 400

    camera.name = name
    camera.location = (data.get('location') or '').strip()
    camera.camera_type = camera_type
    if camera_type == 'ip':
        camera.url = (data.get('url') or '').strip()
        camera.username = (data.get('username') or '').strip()
        camera.password = (data.get('password') or '').strip()
        camera.width = int(data.get('width') or camera.width or 1280)
        camera.height = int(data.get('height') or camera.height or 720)
        camera.fps = int(data.get('fps') or camera.fps or 15)
    else:
        camera.url = None
        camera.username = None
        camera.password = None
    if 'is_active' in data:
        camera.is_active = bool(data.get('is_active'))

    db.session.commit()
    camera_manager.reset(camera_id)  # picks up new URL/credentials on next use

    app_logger.info(f"Camera updated by {current_user.username}: {camera.name}")
    return jsonify({'success': True, 'message': 'Camera updated', 'camera': camera.to_dict()})


@camera_bp.route('/cameras/<int:camera_id>', methods=['DELETE'])
@login_required
def delete_camera(camera_id):
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Admin only'}), 403

    camera = Camera.query.get_or_404(camera_id)
    name = camera.name
    db.session.delete(camera)
    db.session.commit()
    camera_manager.reset(camera_id)

    app_logger.info(f"Camera deleted by {current_user.username}: {name}")
    return jsonify({'success': True, 'message': f'{name} deleted'})


@camera_bp.route('/cameras/<int:camera_id>/test', methods=['POST'])
@login_required
def test_camera(camera_id):
    """Server-side connectivity probe for an IP camera (admin only, from Settings > Cameras)."""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Admin only'}), 403

    camera = Camera.query.get_or_404(camera_id)
    if camera.camera_type != 'ip':
        return jsonify({
            'success': True,
            'available': True,
            'message': 'Webcam cameras are accessed directly by the browser on each device — nothing to test on the server.'
        })

    status = camera_manager.test(_to_config(camera))
    if status['available']:
        return jsonify({
            'success': True,
            'available': True,
            'message': 'Camera is reachable',
            'snapshot_url': f'/api/camera/{camera_id}/snapshot?' + str(int(time.time()))
        })
    return jsonify({
        'success': True,
        'available': False,
        'message': 'Camera did not respond — check the URL/credentials and that it is powered on and reachable on the network.'
    })


# ============================================
# PER-CAMERA STREAM/SNAPSHOT (IP cameras only)
# ============================================

def _load_ip_camera_or_error(camera_id):
    """Returns (camera, error_response). error_response is None on success."""
    camera = Camera.query.get(camera_id)
    if camera is None:
        return None, (jsonify({'success': False, 'message': 'Camera not found'}), 404)
    if camera.camera_type != 'ip':
        return None, (jsonify({
            'success': False,
            'message': 'This is a webcam camera — accessed directly by the browser, not via this endpoint'
        }), 400)
    return camera, None


@camera_bp.route('/camera/<int:camera_id>/status')
@login_required
def camera_status(camera_id):
    camera, error = _load_ip_camera_or_error(camera_id)
    if error:
        return error
    status = camera_manager.get_status(_to_config(camera))
    return jsonify(status)


@camera_bp.route('/camera/<int:camera_id>/snapshot')
@login_required
def camera_snapshot(camera_id):
    """Single snapshot from an IP camera. Used as <img src="/api/camera/<id>/snapshot">."""
    camera, error = _load_ip_camera_or_error(camera_id)
    if error:
        return error

    success, frame = camera_manager.capture_frame(_to_config(camera))

    if success and frame is not None:
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if ret:
            return Response(
                buffer.tobytes(),
                mimetype='image/jpeg',
                headers={
                    'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
                    'X-Camera-Id': str(camera_id)
                }
            )

    return Response('Camera unavailable', status=503, mimetype='text/plain')


@camera_bp.route('/camera/<int:camera_id>/stream')
@login_required
def camera_stream(camera_id):
    """MJPEG stream from an IP camera. Used as <img src="/api/camera/<id>/stream">."""
    camera, error = _load_ip_camera_or_error(camera_id)
    if error:
        return error

    cfg = _to_config(camera)

    def generate_frames():
        app_logger.info(f"🎥 MJPEG stream started for camera {camera_id}")
        frame_count = 0
        error_count = 0
        max_errors = 10

        while True:
            success, frame = camera_manager.capture_frame(cfg)

            if success and frame is not None:
                error_count = 0
                frame_count += 1

                if frame_count == 1 or frame_count % 100 == 0:
                    app_logger.info(f"🎥 Camera {camera_id}: {frame_count} frames served")

                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' +
                           buffer.tobytes() +
                           b'\r\n')
            else:
                error_count += 1
                app_logger.warning(f"⚠️ Camera {camera_id} stream: frame capture failed ({error_count}/{max_errors})")
                if error_count >= max_errors:
                    app_logger.error(f"❌ Camera {camera_id} stream: too many consecutive errors, stopping")
                    break

            time.sleep(1.0 / max(cfg.fps, 1))

        app_logger.info(f"🎥 Camera {camera_id} stream ended after {frame_count} frames")

    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0'}
    )


@camera_bp.route('/camera/<int:camera_id>/reset', methods=['POST'])
@login_required
def reset_camera(camera_id):
    """Force re-check of one camera's availability."""
    camera_manager.reset(camera_id)
    app_logger.info(f"🔄 Camera {camera_id} reset requested")
    return jsonify({'success': True, 'message': f'Camera {camera_id} reset'})
