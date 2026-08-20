"""
Attendance Routes v5.0 - INSTANT RESPONSE
Optimized for real-time face recognition with ZERO lag
Two-stage processing: Instant detection → Async recognition
"""

from flask import Blueprint, render_template, request, jsonify, session
from flask_login import login_required, current_user
from models import db
from models.database import Employee, Attendance, SystemSetting
from models.face_recognition import face_engine
from utils.liveness_detection import liveness_detector
from config import Config
from utils.logger import app_logger
import cv2
import numpy as np
from datetime import datetime, date, time, timedelta
from typing import Optional, Dict, Any, List, Tuple
import base64
import os
import sys
from functools import lru_cache

# ============================================
# BLUEPRINT CONFIGURATION
# ============================================

attendance_bp = Blueprint('attendance', __name__, url_prefix='/attendance')

# ============================================
# CONSTANTS - OPTIMIZED
# ============================================

DEFAULT_WORK_START = time(8, 0, 0)
DEFAULT_LATE_THRESHOLD = 15  # minutes
DEFAULT_HALF_DAY_HOURS = 4.0
DEFAULT_FULL_DAY_HOURS = 8.0


def get_work_start_time():
    """Read WORK_START_TIME live from Config so Settings changes take effect
    immediately, falling back to the hardcoded default if unset/unparsable."""
    try:
        return datetime.strptime(Config.WORK_START_TIME, '%H:%M:%S').time()
    except (ValueError, TypeError, AttributeError):
        return DEFAULT_WORK_START


def get_late_threshold():
    try:
        return int(Config.LATE_THRESHOLD_MINUTES)
    except (ValueError, TypeError):
        return DEFAULT_LATE_THRESHOLD


def get_half_day_hours():
    try:
        return float(Config.HALF_DAY_HOURS)
    except (ValueError, TypeError):
        return DEFAULT_HALF_DAY_HOURS


def get_full_day_hours():
    try:
        return float(Config.FULL_DAY_HOURS)
    except (ValueError, TypeError):
        return DEFAULT_FULL_DAY_HOURS


# ============================================
# GLOBAL CACHES - ULTRA FAST
# ============================================

import threading

# Session tracking
last_recognized_cache = {}
last_recognized_lock = threading.Lock()

# Employee object cache (10 min TTL)
employee_cache = {}
employee_cache_lock = threading.Lock()
EMPLOYEE_CACHE_TTL = 600

# Attendance cache (1 min TTL)
attendance_cache = {}
attendance_cache_lock = threading.Lock()
ATTENDANCE_CACHE_TTL = 60


# ============================================
# IMAGE PROCESSING - OPTIMIZED
# ============================================

def decode_base64_image(image_data: str) -> Optional[np.ndarray]:
    """Decode base64 image - ULTRA FAST"""
    try:
        if ',' in image_data:
            image_data = image_data.split(',')[1]

        image_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return None

        height, width = frame.shape[:2]
        if width > 1280:
            scale = 1280 / width
            new_width = 1280
            new_height = int(height * scale)
            frame = cv2.resize(frame, (new_width, new_height),
                             interpolation=cv2.INTER_AREA)

        return frame

    except Exception as e:
        app_logger.error(f"Image decode error: {e}")
        return None


def get_face_bbox(face_obj) -> Optional[List[int]]:
    """Extract bounding box from face object - FAST"""
    try:
        if face_obj and hasattr(face_obj, 'bbox'):
            bbox = face_obj.bbox.astype(int)
            x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
            return [int(x1), int(y1), int(x2 - x1), int(y2 - y1)]
        return None
    except Exception as e:
        app_logger.error(f"Bbox extraction error: {e}")
        return None


# ============================================
# DATABASE OPERATIONS - CACHED & OPTIMIZED
# ============================================

def get_employee_cached(army_id: str) -> Optional[Employee]:
    """Get employee with aggressive caching - ULTRA FAST"""
    try:
        current_time = datetime.now().timestamp()

        with employee_cache_lock:
            if army_id in employee_cache:
                employee_data, cached_time = employee_cache[army_id]

                if current_time - cached_time < EMPLOYEE_CACHE_TTL:
                    # Return a plain, detached object. Every caller only reads
                    # scalar attributes — no lazy loads, no relationship access.
                    return Employee(**employee_data)
                else:
                    del employee_cache[army_id]

        employee = Employee.query.filter_by(
            army_id=army_id,
            is_active=True
        ).first()

        if employee:
            emp_dict = {
                'id':         employee.id,
                'army_id':    employee.army_id,
                'full_name':  employee.full_name,
                'rank':       employee.rank,
                'unit':       employee.unit,
                'is_active':  employee.is_active,
                'photo_path': employee.photo_path
            }
            with employee_cache_lock:
                employee_cache[army_id] = (emp_dict, current_time)

        return employee

    except Exception as e:
        app_logger.error(f"Employee fetch error: {e}")
        return None


def get_attendance_today_cached(employee_id: int) -> Optional[Dict]:
    """Get today's attendance with caching - FAST"""
    try:
        current_time = datetime.now().timestamp()

        with attendance_cache_lock:
            if employee_id in attendance_cache:
                attendance_data, cached_time = attendance_cache[employee_id]

                if current_time - cached_time < ATTENDANCE_CACHE_TTL:
                    return attendance_data
                else:
                    del attendance_cache[employee_id]

        today = date.today()
        attendance = Attendance.query.filter_by(
            employee_id=employee_id,
            date=today
        ).first()

        if attendance:
            attendance_data = {
                'id': attendance.id,
                'check_in_time': attendance.check_in_time.time() if attendance.check_in_time else None,
                'check_out_time': attendance.check_out_time.time() if attendance.check_out_time else None,
                'check_in_datetime': attendance.check_in_time,
                'check_out_datetime': attendance.check_out_time,
                'status': attendance.status,
                'work_hours': attendance.work_hours
            }
        else:
            attendance_data = None

        with attendance_cache_lock:
            attendance_cache[employee_id] = (attendance_data, current_time)

        return attendance_data

    except Exception as e:
        app_logger.error(f"Attendance fetch error: {e}")
        return None


def invalidate_attendance_cache(employee_id: int):
    """Invalidate attendance cache after update"""
    with attendance_cache_lock:
        if employee_id in attendance_cache:
            del attendance_cache[employee_id]


def save_attendance_photo(employee_army_id: str, frame: np.ndarray) -> str:
    """Save attendance photo - FAST with compression"""
    try:
        current_time = datetime.now()

        photo_filename = f"{employee_army_id}_{current_time.strftime('%Y%m%d_%H%M%S')}.jpg"

        photo_folder = os.path.join('static', 'uploads', 'attendance', str(date.today()))
        os.makedirs(photo_folder, exist_ok=True)

        photo_path = os.path.join(photo_folder, photo_filename)

        cv2.imwrite(photo_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 75])

        return photo_path

    except Exception as e:
        app_logger.error(f"Photo save error: {e}")
        return ""


def calculate_work_hours(check_in: datetime, check_out: datetime) -> float:
    """Calculate work hours - FAST"""
    try:
        if check_in and check_out:
            delta = check_out - check_in
            return round(delta.total_seconds() / 3600, 2)
        return 0.0
    except:
        return 0.0


def determine_attendance_status(work_hours: float, late_minutes: int = 0) -> str:
    """
    Determine attendance status - FAST

    Rules:
    - < 4 hours: half_day
    - >= 8 hours: present
    - 4-8 hours: half_day
    - Late > threshold: late
    """
    # ── Change 1: read thresholds live from Config via the getter helpers
    #    so that Settings-page changes take effect without a server restart.
    if work_hours < get_half_day_hours():
        return 'half_day'
    elif work_hours >= get_full_day_hours():
        return 'present' if late_minutes <= get_late_threshold() else 'late'
    else:
        return 'half_day'


# ============================================
# RESPONSE BUILDERS - CLEAN & CONSISTENT
# ============================================

def build_employee_response(employee: Employee) -> Dict:
    """Build employee data for API response"""
    return {
        'army_id': employee.army_id,
        'name': employee.full_name,
        'rank': employee.rank or 'N/A',
        'unit': employee.unit or 'N/A',
        'photo': employee.photo_path or '/static/img/default-avatar.png'
    }


def build_success_response(
    message: str,
    attendance_type: str,
    employee: Employee,
    attendance_data: Dict,
    confidence: float,
    face_obj: Any,
    is_new_face: bool = False
) -> Tuple[Dict, int]:
    """Build successful attendance response"""

    return jsonify({
        'success': True,
        'message': message,
        'type': attendance_type,
        'employee': build_employee_response(employee),
        'employee_id': employee.army_id,
        'attendance': attendance_data,
        'confidence': round(confidence * 100, 1),
        'face_detected': True,
        'faces_count': 1,
        'bbox': get_face_bbox(face_obj),
        'is_new_face': is_new_face,
        'clear_frame': is_new_face,
        'status': f'{attendance_type.upper()}_SUCCESS'
    }), 200


def build_warning_response(
    message: str,
    warning_type: str,
    employee: Employee,
    confidence: float,
    face_obj: Any,
    is_new_face: bool = False,
    extra_data: Dict = None
) -> Tuple[Dict, int]:
    """Build warning response (already completed, too early, etc)"""

    response = {
        'success': False,
        'message': message,
        'type': warning_type,
        'employee': build_employee_response(employee),
        'employee_id': employee.army_id,
        'confidence': round(confidence * 100, 1),
        'face_detected': True,
        'faces_count': 1,
        'bbox': get_face_bbox(face_obj),
        'is_new_face': is_new_face,
        'clear_frame': is_new_face,
        'status': warning_type.upper()
    }

    if extra_data:
        response.update(extra_data)

    return jsonify(response), 200


def build_error_response(
    message: str,
    status: str,
    face_detected: bool = False,
    bbox: List[int] = None,
    clear_frame: bool = True
) -> Tuple[Dict, int]:
    """Build error response"""

    return jsonify({
        'success': False,
        'message': message,
        'face_detected': face_detected,
        'faces_count': 1 if face_detected else 0,
        'bbox': bbox,
        'clear_frame': clear_frame,
        'status': status
    }), 200


# ============================================
# MAIN ATTENDANCE ROUTE - OPTIMIZED v5.0
# ============================================

@attendance_bp.route('/mark', methods=['POST'])
@login_required
def mark_attendance():
    """
    Mark attendance - INSTANT RESPONSE v5.0

    TWO-STAGE PROCESSING:
    1. INSTANT face detection and recognition (fast)
    2. Smart attendance logic with minimal DB queries
    """
    try:
        # ============================================
        # VALIDATION
        # ============================================

        data = request.get_json()

        if not data or 'image' not in data:
            return build_error_response(
                'No image provided',
                'MISSING_IMAGE',
                clear_frame=True
            )

        auto_mode = data.get('auto_mode', False)
        session_id = session.get('user_id', 'unknown')

        # ============================================
        # STEP 1: DECODE IMAGE
        # ============================================

        frame = decode_base64_image(data['image'])

        if frame is None:
            return build_error_response(
                'Invalid image data',
                'INVALID_IMAGE',
                clear_frame=True
            )

        # ============================================
        # STEP 2: FACE RECOGNITION (INSTANT)
        # ============================================

        employee_id, confidence, face_obj, status_message = face_engine.recognize_face(
            frame,
            return_all_matches=False,
            last_attendance_today=None
        )

        bbox = get_face_bbox(face_obj)

        # ============================================
        # DEBUG LOGGING
        # ============================================

        if app_logger.level <= 20:
            print(f"\n{'='*60}", file=sys.stderr)
            print(f"🔍 ATTENDANCE REQUEST", file=sys.stderr)
            print(f"  Frame shape: {frame.shape}", file=sys.stderr)
            print(f"  Auto mode: {auto_mode}", file=sys.stderr)
            print(f"  Recognition:", file=sys.stderr)
            print(f"    - Employee ID: {employee_id}", file=sys.stderr)
            print(f"    - Confidence: {confidence:.2%}", file=sys.stderr)
            print(f"    - Status: {status_message}", file=sys.stderr)
            print(f"    - Face detected: {face_obj is not None}", file=sys.stderr)
            print(f"{'='*60}\n", file=sys.stderr)

        # ============================================
        # STEP 3: HANDLE NO FACE / NO MATCH
        # ============================================

        if not employee_id or status_message in ["NO_FACE", "NO_MATCH", "NO_REGISTERED_FACES", "ERROR"]:

            last_recognized = last_recognized_cache.get(session_id)
            should_clear = (last_recognized is not None)

            if should_clear:
                with last_recognized_lock:
                    last_recognized_cache[session_id] = None

            if status_message == "NO_FACE":
                message = "No face detected"
            elif status_message == "NO_MATCH":
                message = "Unknown face detected"
            elif status_message == "NO_REGISTERED_FACES":
                message = "No registered faces in database"
            else:
                message = "Recognition error"

            return build_error_response(
                message,
                status_message,
                face_detected=bool(face_obj),
                bbox=bbox,
                clear_frame=should_clear
            )

        # ============================================
        # STEP 4: GET EMPLOYEE (CACHED)
        # ============================================

        employee = get_employee_cached(employee_id)

        if not employee:
            return build_error_response(
                f'Employee {employee_id} not found in database',
                'EMPLOYEE_NOT_FOUND',
                face_detected=True,
                bbox=bbox,
                clear_frame=True
            )

        # ============================================
        # STEP 5: CHECK IF NEW FACE
        # ============================================

        last_recognized = last_recognized_cache.get(session_id)
        is_new_face = (last_recognized != employee_id)

        if is_new_face:
            with last_recognized_lock:
                last_recognized_cache[session_id] = employee_id

        # ============================================
        # STEP 6: HANDLE UI COOLDOWN (1 second)
        # ============================================

        if status_message == "COOLDOWN":
            return build_warning_response(
                f'{employee.full_name} recognized - Processing...',
                'cooldown',
                employee,
                confidence,
                face_obj,
                is_new_face=False
            )

        # ============================================
        # STEP 7: GET ATTENDANCE DATA (CACHED)
        # ============================================

        last_attendance = get_attendance_today_cached(employee.id)

        # ============================================
        # STEP 7.5: LIVENESS CHECK
        # ============================================
        # Was previously hardcoded to 0.85 with no actual check performed.
        # Now runs the real single-frame liveness detector and, when
        # LIVENESS_REQUIRED is set, rejects spoofed (photo/screen) attempts.
        #
        # Debug prints added so the terminal shows exactly what score the
        # detector produced vs. the configured threshold — makes it obvious
        # when liveness is silently rejecting real people (threshold too high)
        # vs. genuinely blocking a photo attack.

        liveness_score = 0.0
        try:
            liveness_score, _liveness_details = liveness_detector.quick_liveness_check(frame)
        except Exception as e:
            app_logger.warning(f"Liveness check error, treating as not live: {e}")
            liveness_score = 0.0

        print(
            f"  Liveness score: {liveness_score:.2f} "
            f"(threshold: {Config.LIVENESS_THRESHOLD}, "
            f"required: {Config.LIVENESS_REQUIRED})"
        )

        if Config.LIVENESS_REQUIRED and liveness_score < Config.LIVENESS_THRESHOLD:
            print(f"  ❌ REJECTED by liveness check")
            return build_error_response(
                'Liveness check failed - please use a live camera, not a photo or screen',
                'LIVENESS_FAILED',
                face_detected=True,
                bbox=bbox
            )

        # ============================================
        # STEP 8: ATTENDANCE LOGIC
        # ============================================

        today = date.today()
        now = datetime.now()

        # Case 1: Already have check-in and check-out
        if last_attendance and last_attendance['check_in_time'] and last_attendance['check_out_time']:
            return build_warning_response(
                f'{employee.full_name} - Attendance already completed today',
                'already_completed',
                employee,
                confidence,
                face_obj,
                is_new_face
            )

        # Case 2: Have check-in, need check-out
        if last_attendance and last_attendance['check_in_time']:
            check_in_datetime = last_attendance['check_in_datetime']
            hours_since = (now - check_in_datetime).total_seconds() / 3600

            if hours_since < get_half_day_hours():
                remaining = get_half_day_hours() - hours_since
                hours_int = int(remaining)
                mins_int = int((remaining - hours_int) * 60)

                return build_warning_response(
                    f'{employee.full_name} - Wait {hours_int}h {mins_int}m for checkout',
                    'too_early_checkout',
                    employee,
                    confidence,
                    face_obj,
                    is_new_face,
                    extra_data={'remaining_hours': round(remaining, 2)}
                )

            # CHECKOUT PROCESS
            try:
                attendance_record = Attendance.query.filter_by(
                    employee_id=employee.id,
                    date=today
                ).first()

                if not attendance_record:
                    return build_error_response(
                        'Attendance record not found',
                        'RECORD_NOT_FOUND',
                        face_detected=True,
                        bbox=bbox
                    )

                photo_path = save_attendance_photo(employee.army_id, frame)

                attendance_record.check_out_time = now
                attendance_record.check_out_photo = photo_path
                attendance_record.liveness_score_out = liveness_score

                work_hours = calculate_work_hours(
                    attendance_record.check_in_time,
                    now
                )
                attendance_record.work_hours = work_hours

                late_minutes = 0
                if attendance_record.status == 'late':
                    # ── Change 2: use get_work_start_time() so the checkout
                    #    late-minutes calculation respects the configured start
                    #    time rather than the hardcoded 08:00 constant.
                    work_start = datetime.combine(today, get_work_start_time())
                    late_minutes = max(0, int(
                        (attendance_record.check_in_time - work_start).total_seconds() / 60
                    ))

                attendance_record.status = determine_attendance_status(work_hours, late_minutes)

                db.session.commit()
                invalidate_attendance_cache(employee.id)

                return build_success_response(
                    f'Check-out successful! {employee.full_name}',
                    'checkout',
                    employee,
                    {
                        'check_in': attendance_record.check_in_time.strftime('%I:%M %p'),
                        'check_out': now.strftime('%I:%M %p'),
                        'work_hours': work_hours,
                        'status': attendance_record.status
                    },
                    confidence,
                    face_obj,
                    is_new_face
                )

            except Exception as e:
                db.session.rollback()
                app_logger.error(f"Checkout error: {e}", exc_info=True)
                return build_error_response(
                    'Checkout failed - database error',
                    'CHECKOUT_ERROR',
                    face_detected=True,
                    bbox=bbox
                )

        # CASE 3: CHECK-IN (First time today)
        try:
            existing_attendance = Attendance.query.filter_by(
                employee_id=employee.id,
                date=today
            ).first()

            if existing_attendance and existing_attendance.check_in_time:
                return build_warning_response(
                    f'{employee.full_name} - Attendance already marked today',
                    'already_checked_in',
                    employee,
                    confidence,
                    face_obj,
                    is_new_face
                )

            photo_path = save_attendance_photo(employee.army_id, frame)

            # ── Change 3: use get_work_start_time() and get_late_threshold()
            #    so the check-in late calculation respects live Config values.
            work_start = datetime.combine(today, get_work_start_time())
            late_minutes = max(0, int((now - work_start).total_seconds() / 60))
            status = 'late' if late_minutes > get_late_threshold() else 'present'

            attendance_record = Attendance(
                employee_id=employee.id,
                check_in_time=now,
                date=today,
                status=status,
                check_in_photo=photo_path,
                liveness_score_in=liveness_score,
                confidence_score=confidence,
                ip_address=request.remote_addr,
                device_info=request.user_agent.string[:200] if request.user_agent else 'Unknown',
                verified_by=current_user.id
            )

            db.session.add(attendance_record)
            db.session.commit()
            invalidate_attendance_cache(employee.id)

            status_msg = f' - {late_minutes} min late' if status == 'late' else ''

            return build_success_response(
                f'Check-in successful! {employee.full_name}{status_msg}',
                'checkin',
                employee,
                {
                    'check_in': now.strftime('%I:%M %p'),
                    'status': status,
                    'late_minutes': late_minutes
                },
                confidence,
                face_obj,
                is_new_face
            )

        except Exception as e:
            db.session.rollback()
            app_logger.error(f"Check-in error: {e}", exc_info=True)

            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                return build_warning_response(
                    f'{employee.full_name} - Attendance already marked today',
                    'duplicate_attendance',
                    employee,
                    confidence,
                    face_obj,
                    is_new_face
                )

            return build_error_response(
                'Check-in failed - database error',
                'CHECKIN_ERROR',
                face_detected=True,
                bbox=bbox
            )

    except Exception as e:
        db.session.rollback()
        app_logger.error(f"Attendance system error: {e}", exc_info=True)

        return jsonify({
            'success': False,
            'message': 'System error - please try again',
            'face_detected': False,
            'clear_frame': True,
            'status': 'SYSTEM_ERROR'
        }), 500


# ============================================
# ADDITIONAL ROUTES - OPTIMIZED
# ============================================

@attendance_bp.route('/')
@login_required
def index():
    """Live attendance page"""
    return render_template('mark_attendance.html')


@attendance_bp.route('/view')
@login_required
def view_attendance():
    """View attendance records - OPTIMIZED QUERY"""
    date_filter   = request.args.get('date',   date.today().isoformat())
    unit_filter   = request.args.get('unit',   '')
    status_filter = request.args.get('status', '')
    search        = request.args.get('search', '').strip()

    try:
        filter_date = date.fromisoformat(date_filter)
    except ValueError:
        filter_date = date.today()

    query = db.session.query(Attendance, Employee).join(
        Employee, Attendance.employee_id == Employee.id
    ).filter(
        Attendance.date == filter_date,
        Employee.is_active == True
    )

    if unit_filter:
        query = query.filter(Employee.unit == unit_filter)
    if status_filter:
        query = query.filter(Attendance.status == status_filter)
    if search:
        escaped_search = search.replace('%', '\\%').replace('_', '\\_')
        query = query.filter(
            db.or_(
                Employee.army_id.like(f'%{escaped_search}%', escape='\\'),
                Employee.full_name.like(f'%{escaped_search}%', escape='\\')
            )
        )

    attendance_records = query.order_by(Attendance.check_in_time.desc()).all()

    units = db.session.query(Employee.unit).distinct().filter(
        Employee.unit.isnot(None),
        Employee.is_active == True
    ).all()
    units = [u[0] for u in units if u[0]]

    total_employees = Employee.query.filter_by(is_active=True).count()
    total_present   = len(attendance_records)

    stats = {
        'total_employees': total_employees,
        'total_present':   total_present,
        'total_absent':    total_employees - total_present,
        'present':         sum(1 for a, e in attendance_records if a.status == 'present'),
        'late':            sum(1 for a, e in attendance_records if a.status == 'late'),
        'half_day':        sum(1 for a, e in attendance_records if a.status == 'half_day'),
        'attendance_rate': round(
            (total_present / total_employees * 100) if total_employees > 0 else 0, 1
        )
    }

    return render_template(
        'view_attendance.html',
        attendance_records=attendance_records,
        stats=stats,
        units=units,
        filter_date=filter_date
    )


@attendance_bp.route('/stats/today')
@login_required
def stats_today():
    """Get today's stats - FAST"""
    try:
        today = date.today()

        total_employees = Employee.query.filter_by(is_active=True).count()

        today_attendance = db.session.query(Attendance).join(
            Employee, Attendance.employee_id == Employee.id
        ).filter(
            Attendance.date == today,
            Employee.is_active == True
        ).all()

        return jsonify({
            'success': True,
            'stats': {
                'total_employees': total_employees,
                'check_ins':       sum(1 for a in today_attendance if a.check_in_time),
                'check_outs':      sum(1 for a in today_attendance if a.check_out_time),
                'present':         sum(1 for a in today_attendance if a.status == 'present'),
                'late':            sum(1 for a in today_attendance if a.status == 'late'),
                'half_day':        sum(1 for a in today_attendance if a.status == 'half_day'),
                'absent':          total_employees - len(today_attendance),
                'attendance_rate': round(
                    (len(today_attendance) / total_employees * 100)
                    if total_employees > 0 else 0, 1
                )
            }
        })

    except Exception as e:
        app_logger.error(f"Stats error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@attendance_bp.route('/recent')
@login_required
def recent_activity():
    """Recent attendance activity - FAST"""
    try:
        today = date.today()
        limit = int(request.args.get('limit', 10))

        recent = db.session.query(Attendance, Employee).join(
            Employee, Attendance.employee_id == Employee.id
        ).filter(
            Attendance.date == today,
            Employee.is_active == True
        ).order_by(
            Attendance.created_at.desc()
        ).limit(limit).all()

        activities = [{
            'employee_id': emp.army_id,
            'name':        emp.full_name,
            'rank':        emp.rank or 'N/A',
            'unit':        emp.unit or 'N/A',
            'photo':       emp.photo_path or '/static/img/default-avatar.png',
            'check_in':    att.check_in_time.strftime('%I:%M %p')  if att.check_in_time  else None,
            'check_out':   att.check_out_time.strftime('%I:%M %p') if att.check_out_time else None,
            'status':      att.status,
            'confidence':  round(att.confidence_score * 100, 1) if att.confidence_score else 0,
            'work_hours':  att.work_hours
        } for att, emp in recent]

        return jsonify({
            'success': True,
            'activities': activities
        })

    except Exception as e:
        app_logger.error(f"Recent activity error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@attendance_bp.route('/clear_cache', methods=['POST'])
@login_required
def clear_cache():
    """Clear all caches - ADMIN"""
    try:
        face_engine.clear_caches()

        last_recognized_cache.clear()
        employee_cache.clear()
        attendance_cache.clear()

        app_logger.info("All caches cleared")

        return jsonify({
            'success': True,
            'message': 'All caches cleared successfully'
        })

    except Exception as e:
        app_logger.error(f"Cache clear error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@attendance_bp.route('/health')
def health_check():
    """Health check endpoint"""
    try:
        from sqlalchemy import text
        db.session.execute(text('SELECT 1'))

        stats = face_engine.get_statistics()

        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'face_engine': 'ready',
            'engine_version': stats.get('version', '5.0'),
            'embeddings': stats['total_embeddings'],
            'instant_detection': stats.get('instant_detection', True),
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        app_logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@attendance_bp.route('/stats/cache')
@login_required
def cache_stats():
    """Get cache statistics - DEBUG"""
    try:
        return jsonify({
            'success': True,
            'cache_stats': {
                'employee_cache_size':        len(employee_cache),
                'attendance_cache_size':      len(attendance_cache),
                'last_recognized_cache_size': len(last_recognized_cache),
                'face_engine_cache_size':     len(face_engine.recognition_cache),
                'total_cached_items': (
                    len(employee_cache) +
                    len(attendance_cache) +
                    len(last_recognized_cache)
                )
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500