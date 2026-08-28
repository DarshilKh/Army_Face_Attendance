"""
Person Movement Routes - Leave/Holiday Out-In Tracking
Officer shows face -> recognized -> mark OUT (reason + date range) or IN (return).
Deliberately separate from Attendance — a leave record never touches daily
check-in/check-out status.
"""

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from models import db
from models.database import Employee, MovementRecord, AuditLog
from models.face_recognition import face_engine
from routes.attendance import decode_base64_image
from utils.logger import app_logger
from config import Config
import cv2
import os
from datetime import datetime, date

movement_bp = Blueprint('movement', __name__, url_prefix='/movement')


def save_movement_photo(army_id: str, direction: str, frame) -> str:
    """Save an out/in snapshot — same pattern as save_attendance_photo()."""
    try:
        folder = os.path.join('static', 'uploads', 'movement', str(date.today()))
        os.makedirs(folder, exist_ok=True)
        filename = f"{army_id}_{direction}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        path = os.path.join(folder, filename)
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return path
    except Exception as e:
        app_logger.error(f"Movement photo save error: {e}")
        return ""


@movement_bp.route('/')
@login_required
def index():
    """Person Movement scan page"""
    return render_template('movement.html', reasons=Config.MOVEMENT_REASONS)


@movement_bp.route('/scan', methods=['POST'])
@login_required
def scan():
    """
    Capture + recognize one face, return the employee plus their current
    out/in status — so the frontend knows whether to show the Mark-Out
    form (reason/dates) or a one-click Mark-Return button.
    """
    try:
        data = request.get_json()
        if not data or 'image' not in data:
            return jsonify({'success': False, 'message': 'No image provided'}), 400

        frame = decode_base64_image(data['image'])
        if frame is None:
            return jsonify({'success': False, 'message': 'Invalid image data'}), 400

        # Reuses the exact same recognition engine as Mark Attendance —
        # only one face matters here, so max_faces=1.
        employee_id, confidence, face_obj, status_message = face_engine.recognize_faces_multi(frame, max_faces=1)[0]

        if not employee_id or status_message in ('NO_FACE', 'NO_MATCH', 'NO_REGISTERED_FACES') \
                or status_message.startswith('ERROR'):
            messages = {
                'NO_FACE': 'No face detected — try again with better lighting',
                'NO_MATCH': 'Unknown face — not a registered employee',
                'NO_REGISTERED_FACES': 'No registered faces in the system',
            }
            return jsonify({'success': False, 'message': messages.get(status_message, 'Recognition error')})

        employee = Employee.query.filter_by(army_id=employee_id, is_active=True).first()
        if not employee:
            return jsonify({'success': False, 'message': f'Employee {employee_id} not found'})

        open_record = MovementRecord.query.filter_by(employee_id=employee.id, status='out').first()

        return jsonify({
            'success': True,
            'employee': {
                'id': employee.id,
                'army_id': employee.army_id,
                'name': employee.full_name,
                'rank': employee.rank or 'N/A',
                'unit': employee.unit or 'N/A',
                'photo': employee.photo_path or '/static/img/default-avatar.png',
            },
            'confidence': round(confidence * 100, 1),
            'currently_out': open_record is not None,
            'open_record': ({
                'id': open_record.id,
                'reason': open_record.reason,
                'start_date': open_record.start_date.isoformat(),
                'end_date': open_record.end_date.isoformat(),
                'out_time': open_record.out_time.strftime('%d %b %Y, %I:%M %p'),
            } if open_record else None),
        })

    except Exception as e:
        app_logger.error(f"Movement scan error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Recognition error — please try again'}), 500


@movement_bp.route('/mark_out', methods=['POST'])
@login_required
def mark_out():
    """Mark an employee OUT — reason + planned return window, with an
    optional snapshot from the same scan for a visual record."""
    try:
        data = request.get_json() or {}
        employee_id = data.get('employee_id')
        reason = (data.get('reason') or '').strip()
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')

        if not employee_id or not reason or not start_date_str or not end_date_str:
            return jsonify({'success': False, 'message': 'Employee, reason, and date range are all required'}), 400

        if reason not in Config.MOVEMENT_REASONS:
            return jsonify({'success': False, 'message': 'Invalid reason'}), 400

        employee = Employee.query.get(employee_id)
        if not employee or not employee.is_active:
            return jsonify({'success': False, 'message': 'Employee not found'}), 404

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid date format'}), 400

        if end_date < start_date:
            return jsonify({'success': False, 'message': 'End date cannot be before start date'}), 400

        existing = MovementRecord.query.filter_by(employee_id=employee.id, status='out').first()
        if existing:
            return jsonify({
                'success': False,
                'message': f'{employee.full_name} is already marked OUT since '
                           f'{existing.out_time.strftime("%d %b %Y")} — mark them IN first.'
            }), 400

        out_photo = ''
        image_data = data.get('image')
        if image_data:
            frame = decode_base64_image(image_data)
            if frame is not None:
                out_photo = save_movement_photo(employee.army_id, 'out', frame)

        record = MovementRecord(
            employee_id=employee.id,
            reason=reason,
            start_date=start_date,
            end_date=end_date,
            out_time=datetime.now(),
            out_photo=out_photo,
            status='out',
            verified_by=current_user.id,
        )
        db.session.add(record)
        db.session.flush()

        audit = AuditLog(
            user_id=current_user.id,
            action='MOVEMENT_OUT',
            table_name='movement_records',
            record_id=record.id,
            new_value=f"{employee.army_id} OUT — {reason}, {start_date} to {end_date}",
            ip_address=request.remote_addr,
        )
        db.session.add(audit)
        db.session.commit()

        app_logger.info(f"Movement OUT: {employee.army_id} - {reason} ({start_date} to {end_date})")

        return jsonify({'success': True, 'message': f'{employee.full_name} marked OUT — {reason}'})

    except Exception as e:
        db.session.rollback()
        app_logger.error(f"Mark out error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to mark out — please try again'}), 500


@movement_bp.route('/mark_in', methods=['POST'])
@login_required
def mark_in():
    """Mark a currently-out employee back IN."""
    try:
        data = request.get_json() or {}
        employee_id = data.get('employee_id')

        if not employee_id:
            return jsonify({'success': False, 'message': 'Employee is required'}), 400

        employee = Employee.query.get(employee_id)
        if not employee:
            return jsonify({'success': False, 'message': 'Employee not found'}), 404

        record = MovementRecord.query.filter_by(employee_id=employee.id, status='out').first()
        if not record:
            return jsonify({'success': False, 'message': f'{employee.full_name} has no active OUT record'}), 400

        in_photo = ''
        image_data = data.get('image')
        if image_data:
            frame = decode_base64_image(image_data)
            if frame is not None:
                in_photo = save_movement_photo(employee.army_id, 'in', frame)

        record.in_time = datetime.now()
        record.in_photo = in_photo
        record.status = 'returned'

        audit = AuditLog(
            user_id=current_user.id,
            action='MOVEMENT_IN',
            table_name='movement_records',
            record_id=record.id,
            new_value=f"{employee.army_id} returned at {record.in_time.strftime('%Y-%m-%d %H:%M')}",
            ip_address=request.remote_addr,
        )
        db.session.add(audit)
        db.session.commit()

        app_logger.info(f"Movement IN: {employee.army_id} returned")

        return jsonify({'success': True, 'message': f'{employee.full_name} marked IN — welcome back!'})

    except Exception as e:
        db.session.rollback()
        app_logger.error(f"Mark in error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to mark in — please try again'}), 500


@movement_bp.route('/currently_out')
@login_required
def currently_out():
    """JSON list of everyone currently out — powers the 'Currently Out' panel on the scan page."""
    records_list = db.session.query(MovementRecord, Employee).join(
        Employee, MovementRecord.employee_id == Employee.id
    ).filter(MovementRecord.status == 'out').order_by(MovementRecord.out_time.desc()).all()

    return jsonify({
        'success': True,
        'records': [{
            'id': r.id,
            'employee_id': e.army_id,
            'name': e.full_name,
            'rank': e.rank or 'N/A',
            'reason': r.reason,
            'start_date': r.start_date.isoformat(),
            'end_date': r.end_date.isoformat(),
            'out_time': r.out_time.strftime('%d %b, %I:%M %p'),
            'photo': e.photo_path or '/static/img/default-avatar.png',
        } for r, e in records_list]
    })


@movement_bp.route('/records')
@login_required
def records():
    """Movement history page — everyone who's ever gone out/come back, with filters."""
    status_filter = request.args.get('status', '')
    search = request.args.get('search', '').strip()

    query = db.session.query(MovementRecord, Employee).join(
        Employee, MovementRecord.employee_id == Employee.id
    )

    if status_filter:
        query = query.filter(MovementRecord.status == status_filter)
    if search:
        escaped_search = search.replace('%', '\\%').replace('_', '\\_')
        query = query.filter(
            db.or_(
                Employee.army_id.like(f'%{escaped_search}%', escape='\\'),
                Employee.full_name.like(f'%{escaped_search}%', escape='\\'),
            )
        )

    records_list = query.order_by(MovementRecord.out_time.desc()).all()
    currently_out_count = sum(1 for r, e in records_list if r.status == 'out')

    return render_template(
        'movement_records.html',
        records=records_list,
        currently_out_count=currently_out_count,
        status_filter=status_filter,
        search=search,
    )
