"""
Employee Registration Routes - Professional Grade
Handles multi-angle photo capture and face registration
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from models import db
from models.database import Employee, AuditLog
from models.face_recognition import face_engine
from utils.logger import app_logger
from utils.image_processing import save_upload_image, preprocess_image, enhance_face_image
from werkzeug.utils import secure_filename
import os
import cv2
import numpy as np
import base64
import csv
import io
import zipfile
import tempfile
import shutil
from datetime import datetime
from typing import Optional, Tuple, List
from config import Config

registration_bp = Blueprint('registration', __name__, url_prefix='/registration')

# Constants
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
MIN_QUALITY_THRESHOLD = 0.3
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def decode_base64_image(base64_string: str) -> Optional[np.ndarray]:
    """
    Decode base64 image string to OpenCV format

    Args:
        base64_string: Base64 encoded image data

    Returns:
        OpenCV image array or None if invalid
    """
    try:
        # Remove data URL prefix if present
        if ',' in base64_string:
            base64_string = base64_string.split(',')[1]

        # Decode base64
        image_bytes = base64.b64decode(base64_string)
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        return image
    except Exception as e:
        app_logger.error(f"Base64 decode error: {e}")
        return None


def save_image_from_base64(base64_data: str, save_path: str) -> bool:
    """
    Save base64 image to disk

    Args:
        base64_data: Base64 encoded image
        save_path: Path to save image

    Returns:
        True if successful, False otherwise
    """
    try:
        image = decode_base64_image(base64_data)
        if image is None:
            return False

        # Create directory if not exists
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        # Save image
        cv2.imwrite(save_path, image)
        app_logger.info(f"Image saved: {save_path}")
        return True

    except Exception as e:
        app_logger.error(f"Failed to save image: {e}")
        return False


def select_best_photo(photos: List[Tuple[str, np.ndarray]]) -> Tuple[str, np.ndarray, float]:
    """
    Select best quality photo from multiple angles

    Args:
        photos: List of (angle_name, image_array) tuples

    Returns:
        Tuple of (best_angle, best_image, quality_score)
    """
    best_angle = None
    best_image = None
    best_score = 0.0

    for angle, image in photos:
        try:
            quality_score, _ = face_engine.get_face_quality_score(image)
            app_logger.info(f"Quality score for {angle}: {quality_score:.2f}")

            if quality_score > best_score:
                best_score = quality_score
                best_image = image
                best_angle = angle
        except Exception as e:
            app_logger.warning(f"Quality check failed for {angle}: {e}")

    return best_angle, best_image, best_score


@registration_bp.route('/')
@login_required
def index():
    """Employee registration page"""
    if current_user.role not in ['admin', 'officer']:
        flash('Access denied', 'error')
        return redirect(url_for('auth.dashboard'))

    return render_template('registration.html', ranks=Config.RANKS)


@registration_bp.route('/check_quality', methods=['POST'])
@login_required
def check_quality():
    """
    Live photo-quality feedback during registration — reuses the same
    face_engine.get_face_quality_score() that select_best_photo() already
    uses server-side, just surfaced to the frontend per angle instead of
    only appearing in the console log.
    """
    try:
        data = request.get_json() or {}
        image = decode_base64_image(data.get('image', ''))

        if image is None:
            return jsonify({'success': False, 'message': 'Invalid image data'}), 400

        quality_score, details = face_engine.get_face_quality_score(image)

        if quality_score >= 0.6:
            tier = 'good'
        elif quality_score >= MIN_QUALITY_THRESHOLD:
            tier = 'fair'
        else:
            tier = 'poor'

        message = details.get('error') if isinstance(details, dict) else None

        return jsonify({
            'success': True,
            'quality_score': round(quality_score, 2),
            'tier': tier,
            'message': message
        })

    except Exception as e:
        app_logger.error(f"Quality check error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


def _finalize_employee_registration(army_id, full_name, rank, unit, department, designation,
                                     phone, email, date_of_joining, photos_data, photo_paths,
                                     created_by):
    """
    Shared core: given decoded photos_data/photo_paths and validated metadata,
    picks the best photo, checks quality, enhances, registers the face
    embedding, and creates the Employee DB record + audit log.

    Used by both single-employee registration (camera capture or manual
    upload) and bulk import, so every registration path gets identical
    quality/validation behavior.

    Returns a dict: {success, message, employee_id?, army_id?, quality_score?, best_angle?}
    """
    try:
        if not photos_data:
            return {'success': False, 'message': 'No photo provided. Please capture or upload a photo.'}

        # Select best quality photo for face registration
        if len(photos_data) > 1:
            app_logger.info("Selecting best quality photo from multiple angles...")
            best_angle, best_image, quality_score = select_best_photo(photos_data)
            primary_photo_path = photo_paths[best_angle]
            app_logger.info(f"Best photo: {best_angle} with quality {quality_score:.2f}")
        else:
            best_angle = photos_data[0][0]
            best_image = photos_data[0][1]
            primary_photo_path = photo_paths[best_angle]
            quality_score, _ = face_engine.get_face_quality_score(best_image)
            app_logger.info(f"Single photo quality: {quality_score:.2f}")

        # Check quality threshold
        if quality_score < MIN_QUALITY_THRESHOLD:
            for path in photo_paths.values():
                try:
                    os.remove(path)
                except Exception:
                    pass
            return {
                'success': False,
                'message': f'Photo quality too low ({quality_score:.0%}). Please use a clearer photo with better lighting.'
            }

        # Auto-enhance best image
        try:
            enhanced_image = enhance_face_image(best_image)
            cv2.imwrite(primary_photo_path, enhanced_image)
            app_logger.info("Photo enhanced successfully")
        except Exception as e:
            app_logger.warning(f"Enhancement failed: {e}, using original")

        # Register face embedding using best photo
        app_logger.info(f"Registering face for: {army_id}")
        success, message, embedding_id = face_engine.register_face(army_id, primary_photo_path)

        if not success:
            for path in photo_paths.values():
                try:
                    os.remove(path)
                except Exception:
                    pass
            return {'success': False, 'message': f'Face registration failed: {message}'}

        app_logger.info(f"Face registered successfully. Embedding ID: {embedding_id}")

        # Parse date of joining
        doj = None
        if date_of_joining:
            try:
                doj = datetime.strptime(date_of_joining, '%Y-%m-%d').date()
            except ValueError:
                app_logger.warning(f"Invalid date format: {date_of_joining}")

        # Create employee record
        employee = Employee(
            army_id=army_id,
            full_name=full_name,
            rank=rank,
            unit=unit,
            department=department,
            designation=designation,
            phone=phone,
            email=email,
            date_of_joining=doj,
            photo_path=primary_photo_path,
            face_embedding_id=embedding_id,
            is_active=True,
            created_by=created_by
        )

        db.session.add(employee)
        db.session.flush()

        audit = AuditLog(
            user_id=created_by,
            action='EMPLOYEE_REGISTER',
            table_name='employees',
            record_id=employee.id,
            new_value=f"ID: {army_id}, Name: {full_name}, Quality: {quality_score:.2f}, Photos: {len(photos_data)}",
            ip_address=request.remote_addr
        )
        db.session.add(audit)
        db.session.commit()

        app_logger.info(f"✓ Employee registered: {army_id} - {full_name}")

        return {
            'success': True,
            'message': f'{full_name} registered successfully!',
            'employee_id': employee.id,
            'army_id': army_id,
            'quality_score': f"{quality_score:.0%}",
            'photos_captured': len(photos_data),
            'best_angle': best_angle
        }

    except Exception as e:
        db.session.rollback()
        app_logger.error(f"Registration error for {army_id}: {e}", exc_info=True)
        for path in photo_paths.values():
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        return {'success': False, 'message': f'Registration error: {str(e)}'}


@registration_bp.route('/register', methods=['POST'])
@login_required
def register_employee():
    """
    Register new employee with multi-angle face photos
    Supports both file upload and base64 capture
    """
    try:
        # Check permissions
        if current_user.role not in ['admin', 'officer']:
            return jsonify({
                'success': False,
                'message': 'Access denied'
            }), 403

        app_logger.info("=== Employee Registration Started ===")

        # Get and validate form data
        army_id = request.form.get('army_id', '').strip()
        full_name = request.form.get('full_name', '').strip()
        rank = request.form.get('rank', '').strip()
        unit = request.form.get('unit', '').strip()
        department = request.form.get('department', '').strip()
        designation = request.form.get('designation', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        date_of_joining = request.form.get('date_of_joining', '').strip()

        app_logger.info(f"Registration request for: {army_id} - {full_name}")

        # Validate required fields
        if not army_id or not full_name:
            return jsonify({
                'success': False,
                'message': 'Employee ID and Full Name are required'
            }), 400

        # Check for duplicate Army ID
        existing = Employee.query.filter_by(army_id=army_id).first()
        if existing:
            return jsonify({
                'success': False,
                'message': f'Employee ID {army_id} already exists'
            }), 400

        # Create upload folder
        upload_folder = os.path.join(Config.UPLOAD_FOLDER, army_id)
        os.makedirs(upload_folder, exist_ok=True)
        app_logger.info(f"Upload folder created: {upload_folder}")

        # Handle photos - Support both base64 and file upload
        photos_data = []
        photo_paths = {}

        # Check for base64 photos (from camera capture)
        if 'photo_front' in request.form:
            app_logger.info("Processing base64 multi-angle photos...")

            angles = ['front', 'left', 'right']
            for angle in angles:
                photo_key = f'photo_{angle}'

                if photo_key not in request.form:
                    return jsonify({
                        'success': False,
                        'message': f'Missing {angle} photo. Please capture all 3 angles.'
                    }), 400

                # Decode base64 image
                base64_data = request.form.get(photo_key)
                image = decode_base64_image(base64_data)

                if image is None:
                    return jsonify({
                        'success': False,
                        'message': f'Invalid {angle} photo data'
                    }), 400

                # Save photo
                filename = f"{army_id}_{angle}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                photo_path = os.path.join(upload_folder, filename)
                cv2.imwrite(photo_path, image)

                photos_data.append((angle, image))
                photo_paths[angle] = photo_path
                app_logger.info(f"Saved {angle} photo: {photo_path}")

        # Check for multi-angle FILE upload (new — same 3-angle shape as camera
        # capture, but from uploaded image files instead of live capture)
        elif any(f'photo_{a}' in request.files for a in ('front', 'left', 'right')):
            app_logger.info("Processing multi-angle uploaded photo files...")

            for angle in ('front', 'left', 'right'):
                file_key = f'photo_{angle}'
                if file_key not in request.files or request.files[file_key].filename == '':
                    continue  # each angle is optional for uploads — at least one required overall

                photo = request.files[file_key]
                file_ext = photo.filename.rsplit('.', 1)[1].lower() if '.' in photo.filename else ''

                if file_ext not in ALLOWED_EXTENSIONS:
                    return jsonify({
                        'success': False,
                        'message': f'{angle.title()} photo: only PNG, JPG, JPEG files are allowed'
                    }), 400

                filename = secure_filename(f"{army_id}_{angle}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
                photo_path = os.path.join(upload_folder, filename)
                photo.save(photo_path)

                image = cv2.imread(photo_path)
                if image is None:
                    os.remove(photo_path)
                    return jsonify({
                        'success': False,
                        'message': f'{angle.title()} photo: invalid image file'
                    }), 400

                photos_data.append((angle, image))
                photo_paths[angle] = photo_path
                app_logger.info(f"Saved uploaded {angle} photo: {photo_path}")

            if not photos_data:
                return jsonify({
                    'success': False,
                    'message': 'No valid photo files uploaded'
                }), 400

        # Check for file upload (traditional method)
        elif 'photo' in request.files:
            app_logger.info("Processing uploaded photo file...")

            photo = request.files['photo']

            if photo.filename == '':
                return jsonify({
                    'success': False,
                    'message': 'No photo selected'
                }), 400

            # Validate file extension
            file_ext = photo.filename.rsplit('.', 1)[1].lower() if '.' in photo.filename else ''

            if file_ext not in ALLOWED_EXTENSIONS:
                return jsonify({
                    'success': False,
                    'message': 'Only PNG, JPG, JPEG files are allowed'
                }), 400

            # Save uploaded file
            filename = secure_filename(f"{army_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
            photo_path = os.path.join(upload_folder, filename)
            photo.save(photo_path)

            # Read image
            image = cv2.imread(photo_path)
            if image is None:
                os.remove(photo_path)
                return jsonify({
                    'success': False,
                    'message': 'Invalid image file'
                }), 400

            photos_data.append(('front', image))
            photo_paths['front'] = photo_path
            app_logger.info(f"Saved uploaded photo: {photo_path}")

        else:
            return jsonify({
                'success': False,
                'message': 'No photo provided. Please capture or upload a photo.'
            }), 400

        result = _finalize_employee_registration(
            army_id, full_name, rank, unit, department, designation,
            phone, email, date_of_joining, photos_data, photo_paths,
            current_user.id
        )
        return jsonify(result), (200 if result.get('success') else 400)

    except Exception as e:
        db.session.rollback()
        app_logger.error(f"Registration error: {e}", exc_info=True)

        # Clean up photos on error
        if 'photo_paths' in locals():
            for path in photo_paths.values():
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except:
                    pass

        return jsonify({
            'success': False,
            'message': f'Registration error: {str(e)}'
        }), 500


@registration_bp.route('/employees')
@login_required
def list_employees():
    """List all employees with filters"""
    try:
        search = request.args.get('search', '').strip()
        unit = request.args.get('unit', '').strip()
        status = request.args.get('status', 'active')
        page = request.args.get('page', 1, type=int)
        per_page = 50

        query = Employee.query

        # Apply search filter
        if search:
            # Escape SQL LIKE special characters to prevent pattern injection
            escaped_search = search.replace('%', '\\%').replace('_', '\\_')
            query = query.filter(
                db.or_(
                    Employee.army_id.like(f'%{escaped_search}%', escape='\\'),
                    Employee.full_name.like(f'%{escaped_search}%', escape='\\'),
                    Employee.phone.like(f'%{escaped_search}%', escape='\\'),
                    Employee.email.like(f'%{escaped_search}%', escape='\\')
                )
            )

        # Apply unit filter
        if unit:
            query = query.filter_by(unit=unit)

        # Apply status filter
        if status == 'active':
            query = query.filter_by(is_active=True)
        elif status == 'inactive':
            query = query.filter_by(is_active=False)

        # Paginate results
        employees_paginated = query.order_by(Employee.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        # Get unique units for filter dropdown
        units = db.session.query(Employee.unit).distinct().filter(
            Employee.unit.isnot(None),
            Employee.unit != ''
        ).all()
        units = sorted([u[0] for u in units if u[0]])

        return render_template(
            'manage_employees.html',
            employees=employees_paginated.items,
            pagination=employees_paginated,
            units=units,
            current_search=search,
            current_unit=unit,
            current_status=status
        )

    except Exception as e:
        app_logger.error(f"Error listing employees: {e}")
        flash('Error loading employees', 'error')
        return redirect(url_for('auth.dashboard'))


def _get_employee_profile_data(employee_id):
    """
    Shared core: employee record + last-30-day attendance history + stats.
    Used by both the full profile page (view_employee) and the JSON summary
    endpoint (employee_summary) used by the Mark Attendance profile modal —
    so both always show the same numbers.
    """
    from models.database import Attendance
    from datetime import date, timedelta

    employee = Employee.query.get_or_404(employee_id)

    thirty_days_ago = date.today() - timedelta(days=30)
    attendance_history = Attendance.query.filter(
        Attendance.employee_id == employee_id,
        Attendance.date >= thirty_days_ago
    ).order_by(Attendance.date.desc()).all()

    total_days = (date.today() - thirty_days_ago).days
    present_days = len(attendance_history)
    attendance_percentage = (present_days / total_days * 100) if total_days > 0 else 0

    stats = {
        'total_days': total_days,
        'present_days': present_days,
        'absent_days': total_days - present_days,
        'attendance_percentage': round(attendance_percentage, 2)
    }

    return employee, attendance_history, stats


@registration_bp.route('/employee/<int:employee_id>')
@login_required
def view_employee(employee_id):
    """View detailed employee profile"""
    try:
        employee, attendance_history, stats = _get_employee_profile_data(employee_id)

        return render_template(
            'employee_detail.html',
            employee=employee,
            attendance_history=attendance_history,
            stats=stats
        )

    except Exception as e:
        app_logger.error(f"Error viewing employee: {e}")
        flash('Employee not found', 'error')
        return redirect(url_for('registration.list_employees'))


@registration_bp.route('/employee/<int:employee_id>/summary')
@login_required
def employee_summary(employee_id):
    """
    JSON profile summary — powers the profile modal opened by clicking a
    card in Mark Attendance's Live Activity Feed, without navigating away
    from the live camera session.
    """
    try:
        from routes.attendance import get_work_start_time
        from datetime import datetime as dt

        def late_minutes_for(att):
            """Stored value if we have it; otherwise computed from check_in_time
            vs. the current work-start setting, for records older than when
            late_minutes started being tracked."""
            if att.late_minutes is not None:
                return att.late_minutes
            if att.status == 'late' and att.check_in_time:
                work_start = dt.combine(att.date, get_work_start_time())
                return max(0, int((att.check_in_time - work_start).total_seconds() / 60))
            return None

        employee, attendance_history, stats = _get_employee_profile_data(employee_id)

        return jsonify({
            'success': True,
            'employee': {
                'id': employee.id,
                'army_id': employee.army_id,
                'full_name': employee.full_name,
                'rank': employee.rank or 'N/A',
                'unit': employee.unit or 'N/A',
                'department': employee.department or 'N/A',
                'designation': employee.designation or 'N/A',
                'phone': employee.phone or 'N/A',
                'email': employee.email or 'N/A',
                'date_of_joining': employee.date_of_joining.isoformat() if employee.date_of_joining else None,
                'photo': employee.photo_path or '/static/img/default-avatar.png',
                'is_active': employee.is_active,
            },
            'stats': stats,
            'recent_attendance': [{
                'date': att.date.isoformat(),
                'check_in': att.check_in_time.strftime('%I:%M %p') if att.check_in_time else None,
                'check_out': att.check_out_time.strftime('%I:%M %p') if att.check_out_time else None,
                'status': att.status,
                'late_minutes': late_minutes_for(att),
            } for att in attendance_history[:10]]
        })

    except Exception as e:
        app_logger.error(f"Error building employee summary: {e}")
        return jsonify({'success': False, 'message': 'Employee not found'}), 404


@registration_bp.route('/employee/<int:employee_id>/edit')
@login_required
def edit_employee(employee_id):
    """Show the edit form for an employee"""
    try:
        employee = Employee.query.get_or_404(employee_id)

        ranks = list(Config.RANKS)
        # Preserve a legacy free-text rank that predates the fixed dropdown,
        # so editing doesn't silently blank it out.
        if employee.rank and employee.rank not in ranks:
            ranks.append(employee.rank)

        units = db.session.query(Employee.unit).distinct().filter(
            Employee.unit.isnot(None), Employee.unit != ''
        ).all()
        units = sorted([u[0] for u in units if u[0]])

        return render_template(
            'edit_employee.html',
            employee=employee,
            ranks=ranks,
            units=units
        )

    except Exception as e:
        app_logger.error(f"Error loading edit form: {e}")
        flash('Employee not found', 'error')
        return redirect(url_for('registration.list_employees'))


@registration_bp.route('/employee/<int:employee_id>/update', methods=['POST'])
@login_required
def update_employee(employee_id):
    """Update employee details, optionally re-registering the face photo"""
    try:
        if current_user.role not in ['admin', 'officer']:
            return jsonify({
                'success': False,
                'message': 'Access denied'
            }), 403

        employee = Employee.query.get_or_404(employee_id)

        new_army_id = request.form.get('army_id', '').strip()
        full_name = request.form.get('full_name', '').strip()

        if not new_army_id or not full_name:
            return jsonify({
                'success': False,
                'message': 'Employee ID and Full Name are required'
            }), 400

        # If Army ID is changing, make sure it doesn't collide with another employee
        if new_army_id != employee.army_id:
            existing = Employee.query.filter(
                Employee.army_id == new_army_id,
                Employee.id != employee.id
            ).first()
            if existing:
                return jsonify({
                    'success': False,
                    'message': f'Employee ID {new_army_id} already exists'
                }), 400

        old_army_id = employee.army_id
        old_values = (
            f"ID: {employee.army_id}, Name: {employee.full_name}, "
            f"Rank: {employee.rank}, Unit: {employee.unit}"
        )

        # Update basic fields
        employee.army_id = new_army_id
        employee.full_name = full_name
        employee.rank = request.form.get('rank', '').strip()
        employee.unit = request.form.get('unit', '').strip()
        employee.department = request.form.get('department', '').strip()
        employee.designation = request.form.get('designation', '').strip()
        employee.phone = request.form.get('phone', '').strip()
        employee.email = request.form.get('email', '').strip()

        date_of_joining = request.form.get('date_of_joining', '').strip()
        if date_of_joining:
            try:
                employee.date_of_joining = datetime.strptime(date_of_joining, '%Y-%m-%d').date()
            except ValueError:
                app_logger.warning(f"Invalid date format: {date_of_joining}")
        else:
            employee.date_of_joining = None

        # If the Army ID changed, the face engine and photo folder need to move
        # to the new ID before any photo update logic runs below.
        if new_army_id != old_army_id:
            face_engine.delete_embedding(old_army_id)

            old_folder = os.path.dirname(employee.photo_path) if employee.photo_path else None
            if old_folder and os.path.exists(old_folder):
                new_folder = os.path.join(Config.UPLOAD_FOLDER, new_army_id)
                try:
                    os.rename(old_folder, new_folder)
                    if employee.photo_path:
                        employee.photo_path = os.path.join(
                            new_folder, os.path.basename(employee.photo_path)
                        )
                except Exception as e:
                    app_logger.warning(f"Could not rename photo folder for ID change: {e}")

            if employee.photo_path and os.path.exists(employee.photo_path):
                face_engine.register_face(new_army_id, employee.photo_path)

        # Handle optional photo re-registration
        update_photo = request.form.get('update_face_photo', 'false').lower() == 'true'
        if update_photo and 'photo' in request.files and request.files['photo'].filename != '':
            photo = request.files['photo']
            file_ext = photo.filename.rsplit('.', 1)[1].lower() if '.' in photo.filename else ''

            if file_ext not in ALLOWED_EXTENSIONS:
                return jsonify({
                    'success': False,
                    'message': 'Only PNG, JPG, JPEG files are allowed'
                }), 400

            upload_folder = os.path.join(Config.UPLOAD_FOLDER, new_army_id)
            os.makedirs(upload_folder, exist_ok=True)

            filename = secure_filename(f"{new_army_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
            new_photo_path = os.path.join(upload_folder, filename)
            photo.save(new_photo_path)

            image = cv2.imread(new_photo_path)
            if image is None:
                os.remove(new_photo_path)
                return jsonify({
                    'success': False,
                    'message': 'Invalid image file'
                }), 400

            quality_score, _ = face_engine.get_face_quality_score(image)
            if quality_score < MIN_QUALITY_THRESHOLD:
                os.remove(new_photo_path)
                return jsonify({
                    'success': False,
                    'message': f'Photo quality too low ({quality_score:.0%}). Please use a clearer photo.'
                }), 400

            try:
                enhanced_image = enhance_face_image(image)
                cv2.imwrite(new_photo_path, enhanced_image)
            except Exception as e:
                app_logger.warning(f"Enhancement failed: {e}, using original")

            # Re-register: delete old embedding(s) and register the new photo
            success, message, embedding_id = face_engine.update_embedding(new_army_id, new_photo_path)
            if not success:
                os.remove(new_photo_path)
                return jsonify({
                    'success': False,
                    'message': f'Face re-registration failed: {message}'
                }), 400

            # Back up the old photo instead of deleting it outright
            old_photo_path = employee.photo_path
            if old_photo_path and os.path.exists(old_photo_path):
                try:
                    backup_path = old_photo_path + f'.bak_{int(datetime.now().timestamp())}'
                    os.rename(old_photo_path, backup_path)
                except Exception as e:
                    app_logger.warning(f"Could not back up old photo: {e}")

            employee.photo_path = new_photo_path
            employee.face_embedding_id = embedding_id

        db.session.flush()

        audit = AuditLog(
            user_id=current_user.id,
            action='EMPLOYEE_UPDATE',
            table_name='employees',
            record_id=employee.id,
            old_value=old_values,
            new_value=f"ID: {employee.army_id}, Name: {employee.full_name}, Rank: {employee.rank}, Unit: {employee.unit}",
            ip_address=request.remote_addr
        )
        db.session.add(audit)
        db.session.commit()

        # Clear caches so the updated details/photo take effect immediately
        try:
            from routes.attendance import employee_cache, attendance_cache
            if old_army_id in employee_cache:
                del employee_cache[old_army_id]
            if employee.army_id in employee_cache:
                del employee_cache[employee.army_id]
            if employee.id in attendance_cache:
                del attendance_cache[employee.id]
            face_engine.clear_caches()
        except Exception as cache_err:
            app_logger.warning(f"Cache clear warning (non-critical): {cache_err}")

        app_logger.info(f"Employee updated: {employee.army_id} - {employee.full_name}")

        return jsonify({
            'success': True,
            'message': f'{employee.full_name} updated successfully',
            'redirect_url': url_for('registration.view_employee', employee_id=employee.id)
        }), 200

    except Exception as e:
        db.session.rollback()
        app_logger.error(f"Update error: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Update error: {str(e)}'
        }), 500


@registration_bp.route('/employee/<int:employee_id>/toggle-status', methods=['POST'])
@login_required
def toggle_employee_status(employee_id):
    """Activate/Deactivate employee"""
    try:
        if current_user.role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Only admin can change status'
            }), 403

        employee = Employee.query.get_or_404(employee_id)
        old_status = employee.is_active
        employee.is_active = not employee.is_active

        db.session.commit()

        # Bug #14b fix: Sync face embeddings with activation status
        # Deactivated employees should NOT be recognized by the face engine
        try:
            if not employee.is_active:
                # Deactivated — remove face embedding so camera stops recognizing them
                face_engine.delete_embedding(employee.army_id)
                app_logger.info(f"Removed face embedding for deactivated employee: {employee.army_id}")
            else:
                # Reactivated — re-register face from existing photo
                if employee.photo_path and os.path.exists(employee.photo_path):
                    face_engine.register_face(employee.army_id, employee.photo_path)
                    app_logger.info(f"Re-registered face for reactivated employee: {employee.army_id}")
                else:
                    app_logger.warning(f"Cannot re-register face for {employee.army_id}: no photo found")

            # Clear in-memory caches
            from routes.attendance import employee_cache, attendance_cache, last_recognized_cache
            if employee.army_id in employee_cache:
                del employee_cache[employee.army_id]
            if employee.id in attendance_cache:
                del attendance_cache[employee.id]
            face_engine.clear_caches()
        except Exception as cache_err:
            app_logger.warning(f"Face embedding/cache sync warning: {cache_err}")

        # Log audit
        audit = AuditLog(
            user_id=current_user.id,
            action='EMPLOYEE_STATUS_CHANGE',
            table_name='employees',
            record_id=employee.id,
            old_value=f"Active: {old_status}",
            new_value=f"Active: {employee.is_active}",
            ip_address=request.remote_addr
        )
        db.session.add(audit)
        db.session.commit()

        status = 'activated' if employee.is_active else 'deactivated'
        app_logger.info(f"Employee {status}: {employee.army_id}")

        return jsonify({
            'success': True,
            'message': f'Employee {status} successfully',
            'is_active': employee.is_active
        }), 200

    except Exception as e:
        db.session.rollback()
        app_logger.error(f"Error toggling status: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@registration_bp.route('/employee/<int:employee_id>/delete', methods=['POST'])
@login_required
def delete_employee(employee_id):
    """Delete employee permanently (admin only)"""
    try:
        if current_user.role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Only admin can delete employees'
            }), 403

        employee = Employee.query.get_or_404(employee_id)

        army_id = employee.army_id
        full_name = employee.full_name
        emp_id = employee.id

        # Delete face embedding
        face_engine.delete_embedding(employee.army_id)

        # Delete employee registration photo files
        if employee.photo_path and os.path.exists(employee.photo_path):
            try:
                # Delete entire folder
                folder = os.path.dirname(employee.photo_path)
                import shutil
                shutil.rmtree(folder, ignore_errors=True)
                app_logger.info(f"Deleted photo folder: {folder}")
            except Exception as e:
                app_logger.warning(f"Could not delete registration photos: {e}")

        # Delete attendance photos from disk (Bug #14a fix)
        # Must be done BEFORE cascade-deleting the employee, since cascade
        # deletes the Attendance records and we lose the photo paths
        try:
            attendance_records = Attendance.query.filter_by(employee_id=employee.id).all()
            deleted_photos = 0
            for att in attendance_records:
                for photo_attr in ['check_in_photo', 'check_out_photo']:
                    photo_path = getattr(att, photo_attr, None)
                    if photo_path and os.path.exists(photo_path):
                        os.remove(photo_path)
                        deleted_photos += 1
            if deleted_photos:
                app_logger.info(f"Deleted {deleted_photos} attendance photos for employee {army_id}")
        except Exception as e:
            app_logger.warning(f"Could not delete attendance photos: {e}")

        # Log audit
        audit = AuditLog(
            user_id=current_user.id,
            action='EMPLOYEE_DELETE',
            table_name='employees',
            record_id=employee.id,
            old_value=f"ID: {army_id}, Name: {full_name}",
            ip_address=request.remote_addr
        )
        db.session.add(audit)

        # Delete employee (cascade will also delete attendance & face_attempts)
        db.session.delete(employee)
        db.session.commit()

        # Clear all in-memory caches so deleted employee data doesn't persist
        try:
            from routes.attendance import (
                employee_cache, attendance_cache, last_recognized_cache
            )
            # Remove this employee from employee cache
            if army_id in employee_cache:
                del employee_cache[army_id]
            # Remove attendance cache for this employee
            if emp_id in attendance_cache:
                del attendance_cache[emp_id]
            # Remove from last recognized cache (check all sessions)
            sessions_to_clear = [
                sid for sid, eid in last_recognized_cache.items()
                if eid == army_id
            ]
            for sid in sessions_to_clear:
                del last_recognized_cache[sid]

            # Clear face engine caches as well
            face_engine.clear_caches()

            app_logger.info(f"Caches cleared for deleted employee: {army_id}")
        except Exception as cache_err:
            app_logger.warning(f"Cache clear warning (non-critical): {cache_err}")

        app_logger.info(f"Employee deleted: {army_id} - {full_name}")

        return jsonify({
            'success': True,
            'message': f'{full_name} deleted successfully'
        }), 200

    except Exception as e:
        db.session.rollback()
        app_logger.error(f"Delete error: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# ═══════════════════════════════════════════════════════════════════════════
# BULK IMPORT — register many employees at once from a CSV of employee
# details + a ZIP of photos.
# ═══════════════════════════════════════════════════════════════════════════

@registration_bp.route('/bulk')
@login_required
def bulk_import_page():
    """Bulk employee import page"""
    if current_user.role not in ['admin', 'officer']:
        flash('Access denied', 'error')
        return redirect(url_for('auth.dashboard'))

    return render_template('bulk_register.html')


@registration_bp.route('/bulk/template')
@login_required
def bulk_import_template():
    """Download a starter CSV template for bulk import"""
    csv_content = (
        "army_id,full_name,rank,unit,department,designation,phone,email,date_of_joining\n"
        "EMP101,John Doe,Sepoy,1st Battalion,Operations,Rifleman,9876543210,john@example.com,2024-01-15\n"
    )
    buffer = io.BytesIO(csv_content.encode('utf-8'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name='bulk_employee_template.csv'
    )


@registration_bp.route('/bulk-import', methods=['POST'])
@login_required
def bulk_import_employees():
    """
    Bulk-register employees from a CSV of employee details + a ZIP of photos.

    CSV columns required: army_id, full_name (rank/unit/department/designation/
    phone/email/date_of_joining are optional, same fields as the manual form).

    ZIP: photos named so the filename contains both the Army ID and the angle,
    e.g. EMP101_front.jpg, EMP101_left.jpg, EMP101_right.jpg (case-insensitive,
    any of png/jpg/jpeg, subfolders OK). At least one photo per employee is
    required; three is ideal for accuracy, matching camera-capture registration.

    Each row is processed through the exact same validation/quality/registration
    logic as a single manual registration (_finalize_employee_registration), so
    results are directly comparable. The batch never fails as a whole — each
    employee succeeds or fails independently, with a per-row result reported.
    """
    if current_user.role not in ['admin', 'officer']:
        return jsonify({'success': False, 'message': 'Access denied'}), 403

    if 'csv_file' not in request.files or request.files['csv_file'].filename == '':
        return jsonify({'success': False, 'message': 'No CSV file provided'}), 400
    if 'photos_zip' not in request.files or request.files['photos_zip'].filename == '':
        return jsonify({'success': False, 'message': 'No photos ZIP file provided'}), 400

    csv_file = request.files['csv_file']
    zip_file = request.files['photos_zip']

    if not csv_file.filename.lower().endswith('.csv'):
        return jsonify({'success': False, 'message': 'CSV file must have a .csv extension'}), 400
    if not zip_file.filename.lower().endswith('.zip'):
        return jsonify({'success': False, 'message': 'Photos file must be a .zip archive'}), 400

    extract_dir = tempfile.mkdtemp(prefix='bulk_import_')
    results = []

    try:
        # Parse CSV
        try:
            csv_text = csv_file.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            return jsonify({'success': False, 'message': 'CSV file must be UTF-8 encoded'}), 400

        reader = csv.DictReader(io.StringIO(csv_text))
        required_cols = {'army_id', 'full_name'}
        available_cols = set(c.strip() for c in (reader.fieldnames or []))
        if not required_cols.issubset(available_cols):
            return jsonify({
                'success': False,
                'message': f'CSV must include at least these columns: {", ".join(sorted(required_cols))}'
            }), 400
        rows = list(reader)

        if not rows:
            return jsonify({'success': False, 'message': 'CSV file has no employee rows'}), 400

        # Extract ZIP
        try:
            with zipfile.ZipFile(zip_file, 'r') as zf:
                zf.extractall(extract_dir)
        except zipfile.BadZipFile:
            return jsonify({'success': False, 'message': 'Photos file is not a valid ZIP archive'}), 400

        # Index every image file in the extracted archive (searched recursively
        # in case photos are organized into subfolders)
        all_files = []
        for root, _, files in os.walk(extract_dir):
            for f in files:
                if '.' in f and f.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS:
                    all_files.append(os.path.join(root, f))

        def find_angle_photo(army_id_lower, angle):
            """Find a photo file whose name contains both the army_id and the angle."""
            for path in all_files:
                name = os.path.basename(path).lower()
                if army_id_lower in name and angle in name:
                    return path
            return None

        for i, row in enumerate(rows, start=1):
            army_id = (row.get('army_id') or '').strip()
            full_name = (row.get('full_name') or '').strip()

            if not army_id or not full_name:
                results.append({
                    'row': i, 'army_id': army_id or '(blank)', 'success': False,
                    'message': 'Missing army_id or full_name'
                })
                continue

            if Employee.query.filter_by(army_id=army_id).first():
                results.append({
                    'row': i, 'army_id': army_id, 'success': False,
                    'message': f'Employee ID {army_id} already exists'
                })
                continue

            army_id_lower = army_id.lower()
            photos_data = []
            photo_paths = {}
            upload_folder = os.path.join(Config.UPLOAD_FOLDER, army_id)
            os.makedirs(upload_folder, exist_ok=True)

            for angle in ('front', 'left', 'right'):
                src_path = find_angle_photo(army_id_lower, angle)
                if not src_path:
                    continue
                image = cv2.imread(src_path)
                if image is None:
                    continue
                dest_filename = f"{army_id}_{angle}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                dest_path = os.path.join(upload_folder, dest_filename)
                cv2.imwrite(dest_path, image)
                photos_data.append((angle, image))
                photo_paths[angle] = dest_path

            if not photos_data:
                results.append({
                    'row': i, 'army_id': army_id, 'success': False,
                    'message': f'No matching photos found in ZIP (expected filenames containing '
                               f'"{army_id}" and "front"/"left"/"right")'
                })
                continue

            outcome = _finalize_employee_registration(
                army_id, full_name,
                (row.get('rank') or '').strip(),
                (row.get('unit') or '').strip(),
                (row.get('department') or '').strip(),
                (row.get('designation') or '').strip(),
                (row.get('phone') or '').strip(),
                (row.get('email') or '').strip(),
                (row.get('date_of_joining') or '').strip(),
                photos_data, photo_paths, current_user.id
            )
            results.append({'row': i, 'army_id': army_id, **outcome})

        succeeded = sum(1 for r in results if r.get('success'))
        failed = len(results) - succeeded

        app_logger.info(f"Bulk import complete: {succeeded} succeeded, {failed} failed out of {len(results)}")

        return jsonify({
            'success': True,
            'total': len(results),
            'succeeded': succeeded,
            'failed': failed,
            'results': results
        }), 200

    except Exception as e:
        app_logger.error(f"Bulk import error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Bulk import error: {str(e)}'}), 500

    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)