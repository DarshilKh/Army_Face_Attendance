from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from models import db
from models.database import User, AuditLog
from utils.logger import app_logger
from datetime import datetime
import re
import os

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
                # Bug #12 fix: Prevent open redirect — only allow relative URLs
                if next_page:
                    from urllib.parse import urlparse
                    parsed = urlparse(next_page)
                    if parsed.netloc or parsed.scheme:
                        next_page = None  # Reject absolute URLs
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
    from datetime import date

    # Get statistics
    total_employees = Employee.query.filter_by(is_active=True).count()

    today = date.today()
    today_attendance = Attendance.query.filter_by(date=today).count()
    today_present    = Attendance.query.filter_by(date=today, status='present').count()
    today_late       = Attendance.query.filter_by(date=today, status='late').count()
    today_absent     = total_employees - today_attendance

    # ── Bug fix: recent attendance was showing deleted/deactivated employees
    #    The original query joined Employee but never filtered on is_active,
    #    so attendance rows tied to employees that had since been deleted or
    #    deactivated still appeared in the dashboard's "Recent Attendance"
    #    table.  Adding Employee.is_active == True removes them.
    # ─────────────────────────────────────────────────────────────────────────
    recent_attendance = db.session.query(Attendance, Employee).join(
        Employee, Attendance.employee_id == Employee.id
    ).filter(
        Employee.is_active == True          # ← exclude deactivated employees
    ).order_by(Attendance.check_in_time.desc()).limit(10).all()

    stats = {
        'total_employees':  total_employees,
        'today_attendance': today_attendance,
        'today_present':    today_present,
        'today_late':       today_late,
        'today_absent':     today_absent,
        'attendance_rate':  round(
            (today_attendance / total_employees * 100) if total_employees > 0 else 0, 1
        ),
    }

    return render_template('dashboard.html',
                           stats=stats,
                           recent_attendance=recent_attendance)


@auth_bp.route('/settings')
@login_required
def settings():
    """System settings page — loads current config values"""
    if current_user.role != 'admin':
        flash('Access denied. Admin only.', 'error')
        return redirect(url_for('auth.dashboard'))

    # Load current settings from DB, fallback to Config defaults
    current_settings = _load_settings()
    return render_template('settings.html', settings=current_settings)


def _load_settings():
    """Load settings from system_settings table with Config defaults as fallback"""
    from config import Config

    defaults = {
        'threshold':           str(Config.FACE_THRESHOLD),
        'duplicate_threshold':  str(Config.DUPLICATE_FACE_THRESHOLD),
        'min_face_size':       str(Config.MIN_FACE_SIZE),
        'liveness_detection':  str(Config.LIVENESS_REQUIRED).lower(),
        'work_start':          Config.WORK_START_TIME,
        'work_end':            Config.WORK_END_TIME,
        'late_threshold':      str(Config.LATE_THRESHOLD_MINUTES),
        'half_day_hours':      str(Config.HALF_DAY_HOURS),
        'full_day_hours':      str(Config.FULL_DAY_HOURS),
        'session_timeout':     str(Config.SESSION_TIMEOUT),
        'max_login_attempts':  str(Config.MAX_LOGIN_ATTEMPTS),
        'log_level':           Config.LOG_LEVEL,
        'multi_angle_registration': str(Config.MULTI_ANGLE_REGISTRATION).lower(),
        'auto_backup':         str(Config.AUTO_BACKUP_ENABLED).lower(),
        'backup_interval':     str(Config.BACKUP_INTERVAL_HOURS),
        'backup_retention':    str(Config.BACKUP_RETENTION_DAYS),
        'auto_checkout':       str(Config.AUTO_CHECKOUT_ENABLED).lower(),
        'auto_checkout_time':  Config.AUTO_CHECKOUT_TIME[:5],  # HH:MM for the <input type="time">
    }

    # Override with any values from the database
    try:
        from models.database import SystemSetting
        db_settings = SystemSetting.query.all()
        for s in db_settings:
            if s.setting_key in defaults:
                defaults[s.setting_key] = s.setting_value
    except Exception as e:
        app_logger.warning(f"Could not load DB settings, using defaults: {e}")

    return defaults


def apply_db_settings_on_startup():
    """Load saved settings from the DB and apply them to Config — called
    once at app startup so Settings changes survive a server restart
    instead of only living in memory until the next reload."""
    try:
        settings = _load_settings()
        _apply_settings_to_config(settings)
        app_logger.info("✓ Applied saved settings from database")
    except Exception as e:
        app_logger.warning(f"Could not apply DB settings on startup: {e}")


@auth_bp.route('/settings/save', methods=['POST'])
@login_required
def save_settings():
    """Save settings to database and update runtime config"""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Admin only'}), 403

    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400

        from models.database import SystemSetting
        from config import Config

        saved_keys = []
        for key, value in data.items():
            # Update or create setting in database
            setting = SystemSetting.query.filter_by(setting_key=key).first()
            if setting:
                setting.setting_value = str(value)
                setting.updated_by = current_user.id
            else:
                setting = SystemSetting(
                    setting_key=key,
                    setting_value=str(value),
                    updated_by=current_user.id
                )
                db.session.add(setting)
            saved_keys.append(key)

        db.session.commit()

        # Update runtime Config values
        _apply_settings_to_config(data)

        # Audit log
        audit = AuditLog(
            user_id=current_user.id,
            action='SETTINGS_UPDATE',
            table_name='system_settings',
            new_value=str(saved_keys),
            ip_address=request.remote_addr
        )
        db.session.add(audit)
        db.session.commit()

        app_logger.info(f"Settings updated by {current_user.username}: {saved_keys}")

        return jsonify({
            'success': True,
            'message': 'Settings saved successfully',
            'updated_keys': saved_keys
        })

    except Exception as e:
        db.session.rollback()
        app_logger.error(f"Error saving settings: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


def _apply_settings_to_config(data):
    """Apply saved settings to runtime Config for immediate effect"""
    from config import Config
    # ── Fix 4a: wire log-level changes through to the live logger so that
    #    a Settings-page change takes effect immediately without a restart.
    from utils.logger import set_log_level

    if 'log_level' in data:
        set_log_level(data['log_level'])

    def to_bool(v):
        return str(v).lower() in ('true', '1', 'on')

    def to_hms(v):
        """Normalize an <input type="time"> value ('HH:MM') to 'HH:MM:SS'."""
        v = str(v)
        return v if v.count(':') == 2 else f'{v}:00'

    config_map = {
        'threshold':           ('FACE_THRESHOLD',        float),
        'duplicate_threshold':  ('DUPLICATE_FACE_THRESHOLD', float),
        'min_face_size':       ('MIN_FACE_SIZE',         int),
        'liveness_detection':  ('LIVENESS_REQUIRED',     to_bool),
        'work_start':          ('WORK_START_TIME',       str),
        'work_end':            ('WORK_END_TIME',         str),
        'late_threshold':      ('LATE_THRESHOLD_MINUTES', int),
        'half_day_hours':      ('HALF_DAY_HOURS',        float),
        'full_day_hours':      ('FULL_DAY_HOURS',        float),
        'session_timeout':     ('SESSION_TIMEOUT',       int),
        'max_login_attempts':  ('MAX_LOGIN_ATTEMPTS',    int),
        'log_level':           ('LOG_LEVEL',             str),
        'multi_angle_registration': ('MULTI_ANGLE_REGISTRATION', to_bool),
        'auto_backup':         ('AUTO_BACKUP_ENABLED',   to_bool),
        'backup_interval':     ('BACKUP_INTERVAL_HOURS', int),
        'backup_retention':    ('BACKUP_RETENTION_DAYS', int),
        'auto_checkout':       ('AUTO_CHECKOUT_ENABLED', to_bool),
        'auto_checkout_time':  ('AUTO_CHECKOUT_TIME',    to_hms),
    }

    for key, value in data.items():
        if key in config_map:
            attr_name, converter = config_map[key]
            try:
                setattr(Config, attr_name, converter(value))
            except (ValueError, TypeError) as e:
                app_logger.warning(f"Could not apply setting {key}={value}: {e}")

    # Camera configuration is no longer part of this form — cameras are
    # managed individually via Settings > Cameras (routes/camera.py CRUD),
    # each with its own URL/credentials/resolution/FPS stored in the
    # `cameras` table.


@auth_bp.route('/settings/backup_now', methods=['POST'])
@login_required
def backup_now():
    """Trigger an immediate mysqldump backup — the real implementation
    behind the Settings > System Actions 'Backup Database Now' button
    (previously a stub alert('not yet implemented'))."""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Admin only'}), 403

    from utils.backup import run_database_backup, prune_old_backups

    success, result = run_database_backup()
    if success:
        prune_old_backups()

    audit = AuditLog(
        user_id=current_user.id,
        action='MANUAL_BACKUP',
        table_name='system',
        new_value=result if success else f'FAILED: {result}',
        ip_address=request.remote_addr
    )
    db.session.add(audit)
    db.session.commit()

    if success:
        return jsonify({'success': True, 'message': f'Backup created: {os.path.basename(result)}'})
    return jsonify({'success': False, 'message': f'Backup failed: {result}'}), 500


@auth_bp.route('/settings/reset', methods=['POST'])
@login_required
def reset_settings():
    """Wipe every saved Settings-page override and restore live Config to
    its true startup defaults (config.SETTINGS_DEFAULTS) — the real
    implementation behind 'Reset to Default Settings' (previously a stub)."""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Admin only'}), 403

    from models.database import SystemSetting
    from config import Config, SETTINGS_DEFAULTS

    SystemSetting.query.delete()

    for attr_name, default_value in SETTINGS_DEFAULTS.items():
        setattr(Config, attr_name, default_value)

    audit = AuditLog(
        user_id=current_user.id,
        action='SETTINGS_RESET',
        table_name='system_settings',
        new_value='All settings reset to defaults',
        ip_address=request.remote_addr
    )
    db.session.add(audit)
    db.session.commit()

    app_logger.info(f"Settings reset to defaults by {current_user.username}")
    return jsonify({'success': True, 'message': 'Settings reset to defaults'})


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change password"""
    if request.method == 'POST':
        from config import Config

        current_password = request.form.get('current_password')
        new_password     = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not current_user.check_password(current_password):
            flash('Current password is incorrect', 'error')
            return redirect(url_for('auth.change_password'))

        if new_password != confirm_password:
            flash('New passwords do not match', 'error')
            return redirect(url_for('auth.change_password'))

        if len(new_password) < Config.MIN_PASSWORD_LENGTH:
            flash(f'Password must be at least {Config.MIN_PASSWORD_LENGTH} characters', 'error')
            return redirect(url_for('auth.change_password'))

        # Password strength check
        if (not re.search(r'[A-Z]', new_password)
                or not re.search(r'[a-z]', new_password)
                or not re.search(r'[0-9]', new_password)):
            flash('Password must contain uppercase, lowercase, and numbers', 'error')
            return redirect(url_for('auth.change_password'))

        if Config.REQUIRE_SPECIAL_CHAR and not re.search(r'[^A-Za-z0-9]', new_password):
            flash('Password must contain at least one special character', 'error')
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