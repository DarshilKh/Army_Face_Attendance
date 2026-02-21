from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db
from models.database import User, AuditLog
from utils.logger import app_logger
from datetime import datetime
import re

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    """Home page - redirect to dashboard if logged in"""
    if current_user.is_authenticated:
        return redirect(url_for('auth.dashboard'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if current_user.is_authenticated:
        return redirect(url_for('auth.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)

        if not username or not password:
            flash('कृपया Username और Password दर्ज करें / Please enter username and password', 'error')
            return render_template('login.html')

        user = User.query.filter_by(username=username).first()

        if user and user.is_active:
            if user.failed_login_attempts >= 3:
                flash('आपका account lock है। Admin से संपर्क करें / Account locked. Contact admin', 'error')
                app_logger.warning(f"Login attempt on locked account: {username}")
                return render_template('login.html')

            if user.check_password(password):
                # Reset failed attempts
                user.failed_login_attempts = 0
                user.last_login = datetime.utcnow()
                db.session.commit()

                # Login user
                login_user(user, remember=remember)

                # Log audit
                audit = AuditLog(
                    user_id=user.id,
                    action='LOGIN',
                    ip_address=request.remote_addr,
                    user_agent=request.user_agent.string
                )
                db.session.add(audit)
                db.session.commit()

                app_logger.info(f"User logged in: {username}")
                flash(f'स्वागत है {user.full_name} / Welcome {user.full_name}', 'success')

                next_page = request.args.get('next')
                return redirect(next_page if next_page else url_for('auth.dashboard'))
            else:
                # Increment failed attempts
                user.failed_login_attempts += 1
                db.session.commit()

                flash(f'गलत Password / Invalid password (Attempts: {user.failed_login_attempts}/3)', 'error')
                app_logger.warning(f"Failed login attempt for user: {username}")
        else:
            flash('User नहीं मिला या inactive है / User not found or inactive', 'error')
            app_logger.warning(f"Login attempt for non-existent user: {username}")

        return render_template('login.html')

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """Logout user"""
    # Log audit
    audit = AuditLog(
        user_id=current_user.id,
        action='LOGOUT',
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string
    )
    db.session.add(audit)
    db.session.commit()

    app_logger.info(f"User logged out: {current_user.username}")
    logout_user()
    flash('Successfully logged out', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard"""
    from models.database import Employee, Attendance
    from sqlalchemy import func
    from datetime import date, timedelta

    # Get statistics
    total_employees = Employee.query.filter_by(is_active=True).count()

    today = date.today()
    today_attendance = Attendance.query.filter_by(date=today).count()
    today_present = Attendance.query.filter_by(date=today, status='present').count()
    today_late = Attendance.query.filter_by(date=today, status='late').count()
    today_absent = total_employees - today_attendance

    # Monthly statistics
    first_day = today.replace(day=1)
    monthly_attendance = db.session.query(
        func.date(Attendance.date).label('date'),
        func.count(Attendance.id).label('count')
    ).filter(
        Attendance.date >= first_day,
        Attendance.date <= today
    ).group_by(func.date(Attendance.date)).all()

    # Recent attendance (last 10)
    recent_attendance = db.session.query(Attendance, Employee).join(
        Employee, Attendance.employee_id == Employee.id
    ).order_by(Attendance.check_in_time.desc()).limit(10).all()

    # Get units for filter
    units = db.session.query(Employee.unit).distinct().filter(
        Employee.unit.isnot(None),
        Employee.is_active == True
    ).all()
    units = [u[0] for u in units if u[0]]

    stats = {
        'total_employees': total_employees,
        'today_attendance': today_attendance,
        'today_present': today_present,
        'today_late': today_late,
        'today_absent': today_absent,
        'attendance_rate': round((today_attendance / total_employees * 100) if total_employees > 0 else 0, 1),
        'monthly_data': [{'date': str(m.date), 'count': m.count} for m in monthly_attendance]
    }

    return render_template('dashboard.html',
                           stats=stats,
                           recent_attendance=recent_attendance,
                           units=units)
@auth_bp.route('/settings')
@login_required
def settings():
    """System settings page"""
    if current_user.role != 'admin':
        flash('Access denied. Admin only.', 'error')
        return redirect(url_for('auth.dashboard'))
    return render_template('settings.html')



@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change password"""
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not current_user.check_password(current_password):
            flash('Current password is incorrect', 'error')
            return redirect(url_for('auth.change_password'))

        if new_password != confirm_password:
            flash('New passwords do not match', 'error')
            return redirect(url_for('auth.change_password'))

        if len(new_password) < 8:
            flash('Password must be at least 8 characters', 'error')
            return redirect(url_for('auth.change_password'))

        # Password strength check
        if not re.search(r'[A-Z]', new_password) or not re.search(r'[a-z]', new_password) or not re.search(r'[0-9]',
                                                                                                           new_password):
            flash('Password must contain uppercase, lowercase, and numbers', 'error')
            return redirect(url_for('auth.change_password'))

        current_user.set_password(new_password)
        db.session.commit()

        # Log audit
        audit = AuditLog(
            user_id=current_user.id,
            action='PASSWORD_CHANGE',
            ip_address=request.remote_addr
        )
        db.session.add(audit)
        db.session.commit()

        flash('Password changed successfully', 'success')
        app_logger.info(f"Password changed for user: {current_user.username}")
        return redirect(url_for('auth.dashboard'))

    return render_template('change_password.html')
