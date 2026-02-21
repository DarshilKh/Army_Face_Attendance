"""
Employee Registration Routes - Professional Grade
Handles multi-angle photo capture and face registration
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
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

    return render_template('registration.html')


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
            # Clean up photos
            for path in photo_paths.values():
                try:
                    os.remove(path)
                except:
                    pass

            return jsonify({
                'success': False,
                'message': f'Photo quality too low ({quality_score:.0%}). Please take a clearer photo with better lighting.'
            }), 400

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
            # Clean up photos
            for path in photo_paths.values():
                try:
                    os.remove(path)
                except:
                    pass

            return jsonify({
                'success': False,
                'message': f'Face registration failed: {message}'
            }), 400

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
            created_by=current_user.id
        )

        db.session.add(employee)
        db.session.flush()

        # Log audit trail
        audit = AuditLog(
            user_id=current_user.id,
            action='EMPLOYEE_REGISTER',
            table_name='employees',
            record_id=employee.id,
            new_value=f"ID: {army_id}, Name: {full_name}, Quality: {quality_score:.2f}, Photos: {len(photos_data)}",
            ip_address=request.remote_addr
        )
        db.session.add(audit)
        db.session.commit()

        app_logger.info(f"✓ Employee registered: {army_id} - {full_name} by {current_user.username}")

        return jsonify({
            'success': True,
            'message': f'✓ {full_name} registered successfully!',
            'employee_id': employee.id,
            'army_id': army_id,
            'quality_score': f"{quality_score:.0%}",
            'photos_captured': len(photos_data),
            'best_angle': best_angle
        }), 200

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
            query = query.filter(
                db.or_(
                    Employee.army_id.like(f'%{search}%'),
                    Employee.full_name.like(f'%{search}%'),
                    Employee.phone.like(f'%{search}%'),
                    Employee.email.like(f'%{search}%')
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


@registration_bp.route('/employee/<int:employee_id>')
@login_required
def view_employee(employee_id):
    """View detailed employee profile"""
    try:
        employee = Employee.query.get_or_404(employee_id)

        # Get attendance history (last 30 days)
        from models.database import Attendance
        from datetime import date, timedelta

        thirty_days_ago = date.today() - timedelta(days=30)
        attendance_history = Attendance.query.filter(
            Attendance.employee_id == employee_id,
            Attendance.date >= thirty_days_ago
        ).order_by(Attendance.date.desc()).all()

        # Calculate attendance stats
        total_days = (date.today() - thirty_days_ago).days
        present_days = len(attendance_history)
        attendance_percentage = (present_days / total_days * 100) if total_days > 0 else 0

        stats = {
            'total_days': total_days,
            'present_days': present_days,
            'absent_days': total_days - present_days,
            'attendance_percentage': round(attendance_percentage, 2)
        }

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

        # Delete face embedding
        face_engine.delete_embedding(employee.army_id)

        # Delete photo files
        if employee.photo_path and os.path.exists(employee.photo_path):
            try:
                # Delete entire folder
                folder = os.path.dirname(employee.photo_path)
                import shutil
                shutil.rmtree(folder, ignore_errors=True)
                app_logger.info(f"Deleted photo folder: {folder}")
            except Exception as e:
                app_logger.warning(f"Could not delete photos: {e}")

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

        # Delete employee
        db.session.delete(employee)
        db.session.commit()

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
