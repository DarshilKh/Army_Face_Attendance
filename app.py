from flask import Flask, g
from flask_login import LoginManager
from config import Config
from models import db, init_app as init_models
from routes import register_blueprints
from utils.logger import app_logger
import os
import time
from datetime import timedelta


def create_app():
    """Application factory pattern"""
    app = Flask(__name__)

    # Load configuration
    app.config.from_object(Config)

    # Additional Flask configurations
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
    app.config['UPLOAD_EXTENSIONS'] = ['.jpg', '.jpeg', '.png']
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=Config.SESSION_TIMEOUT)

    # Initialize database and login manager
    init_models(app)

    # Register all blueprints
    register_blueprints(app)

    # Create required directories
    directories = [
        'logs',
        'face_embeddings',
        'static/uploads/employees',
        'static/uploads/attendance',
        'static/css',
        'static/js',
        'static/images'
    ]

    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        app_logger.info(f"Directory created/verified: {directory}")

    # Initialize face recognition engine on startup
    with app.app_context():
        try:
            from models.face_recognition import face_engine
            app_logger.info("✓ Face recognition engine initialized successfully")
        except Exception as e:
            app_logger.error(f"✗ Failed to initialize face recognition engine: {e}")

    # Initialize camera manager - test network camera availability in the
    # background so a slow/unreachable camera can never delay server startup.
    def _check_camera_in_background():
        try:
            from utils.camera import camera_manager
            cam_status = camera_manager.get_camera_status()
            if cam_status['source'] == 'network':
                app_logger.info(f"✓ Camera: Network camera ACTIVE at {Config.CAMERA_URL}")
            else:
                app_logger.info(f"✓ Camera: System webcam ACTIVE (network camera at {Config.CAMERA_URL} unavailable)")
        except Exception as e:
            app_logger.error(f"✗ Camera initialization error: {e}")

    import threading
    threading.Thread(target=_check_camera_in_background, daemon=True).start()

    # ==================== CACHE BUSTING ====================
    # Prevent browser from caching old files
    @app.context_processor
    def inject_cache_buster():
        """Add cache-busting version to all templates"""
        return {
            'cache_version': int(time.time()),  # Timestamp for cache busting
            'app_version': '1.0.0',
            'get_current_date': lambda: __import__('datetime').date.today(),
            'timedelta': timedelta
        }

    @app.after_request
    def add_no_cache_headers(response):
        """Force browser to always fetch fresh content"""
        # Disable all caching
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'

        # Security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'

        # Add ETag with timestamp to force reload
        if response.status_code == 200:
            response.headers['ETag'] = f'"{int(time.time())}"'

        # Log slow requests
        if hasattr(g, 'start_time'):
            duration = time.time() - g.start_time
            if duration > 1.0:
                app_logger.warning(f"Slow request: {duration:.2f}s - {g.get('endpoint', 'unknown')}")

        return response

    # =======================================================

    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        app_logger.warning(f"404 Error: {error}")
        from flask import render_template
        return render_template('error.html',
                               error_code=404,
                               error_message="Page not found / पेज नहीं मिला"), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app_logger.error(f"500 Error: {error}")
        from flask import render_template
        return render_template('error.html',
                               error_code=500,
                               error_message="Internal server error / सर्वर में त्रुटि"), 500

    @app.errorhandler(403)
    def forbidden_error(error):
        app_logger.warning(f"403 Error: {error}")
        from flask import render_template
        return render_template('error.html',
                               error_code=403,
                               error_message="Access forbidden / पहुँच निषिद्ध"), 403

    @app.errorhandler(413)
    def too_large_error(error):
        app_logger.warning(f"413 Error: File too large")
        from flask import jsonify
        return jsonify({
            'success': False,
            'message': 'File too large. Maximum 16MB / फाइल बहुत बड़ी है'
        }), 413

    # Before request handlers
    @app.before_request
    def before_request():
        """Execute before each request"""
        from flask import session, request

        # Make session permanent
        session.permanent = True
        app.permanent_session_lifetime = timedelta(seconds=Config.SESSION_TIMEOUT)

        # Set request start time for performance monitoring
        g.start_time = time.time()
        g.endpoint = request.endpoint

        # Log request details
        app_logger.debug(f"Request: {request.method} {request.path}")

    # Custom Jinja2 filters
    @app.template_filter('datetime')
    def datetime_filter(value, format='%d-%m-%Y %I:%M %p'):
        """Format datetime objects"""
        if value is None:
            return ''
        return value.strftime(format)

    @app.template_filter('date')
    def date_filter(value, format='%d-%m-%Y'):
        """Format date objects"""
        if value is None:
            return ''
        return value.strftime(format)

    @app.template_filter('time')
    def time_filter(value, format='%I:%M %p'):
        """Format time objects"""
        if value is None:
            return ''
        return value.strftime(format)

    @app.template_filter('duration')
    def duration_filter(seconds):
        """Convert seconds to human readable duration"""
        if seconds is None:
            return ''
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"

    @app.template_filter('percentage')
    def percentage_filter(value, decimals=1):
        """Format as percentage"""
        if value is None:
            return '0%'
        return f"{value:.{decimals}f}%"

    # CLI commands
    @app.cli.command()
    def init_db():
        """Initialize the database"""
        db.create_all()
        print("✓ Database initialized")

    @app.cli.command()
    def create_admin():
        """Create admin user"""
        from models.database import User
        from werkzeug.security import generate_password_hash

        admin = User.query.filter_by(username='admin').first()
        if admin:
            print("✗ Admin user already exists")
            return

        admin = User(
            username='admin',
            password_hash=generate_password_hash('Admin@123', method='scrypt'),
            full_name='System Administrator',
            rank='Major',
            role='admin',
            email='admin@army.mil.in',
            is_active=True
        )

        db.session.add(admin)
        db.session.commit()
        print("✓ Admin user created (username: admin, password: Admin@123)")

    @app.cli.command()
    def reset_embeddings():
        """Reset all face embeddings"""
        embeddings_file = 'face_embeddings/embeddings.pkl'
        if os.path.exists(embeddings_file):
            os.remove(embeddings_file)
            print("✓ Face embeddings reset")
        else:
            print("✗ No embeddings file found")

    @app.cli.command()
    def clear_cache():
        """Clear all Python cache files"""
        import shutil
        cache_dirs = ['__pycache__', 'models/__pycache__', 'routes/__pycache__', 'utils/__pycache__']
        for cache_dir in cache_dirs:
            if os.path.exists(cache_dir):
                shutil.rmtree(cache_dir)
                print(f"✓ Cleared {cache_dir}")
        print("✓ All cache cleared")

    # Startup logging
    app_logger.info("=" * 50)
    app_logger.info("🎖️  ARMY FACE ATTENDANCE SYSTEM")
    app_logger.info("=" * 50)
    app_logger.info("✓ Application initialized successfully")
    app_logger.info(f"✓ Debug mode: {Config.DEBUG}")
    app_logger.info(f"✓ Database: {Config.DB_NAME}")
    app_logger.info("✓ Cache busting: ENABLED")
    app_logger.info("=" * 50)

    return app


# Create application instance
app = create_app()

if __name__ == '__main__':
    # Create database tables if they don't exist
    with app.app_context():
        try:
            db.create_all()
            app_logger.info("✓ Database tables created/verified")

            # ── Fix 5: replay saved Settings into Config on every startup so
            #    changes made via the Settings page are not lost when the dev
            #    server restarts (previously they only lived in memory for the
            #    duration of the process that saved them).
            from routes.auth import apply_db_settings_on_startup
            apply_db_settings_on_startup()
        except Exception as e:
            app_logger.error(f"✗ Database error: {e}")

    # Clear Python cache on startup (optional - comment out if causes issues)
    try:
        import shutil

        for cache_dir in ['__pycache__', 'models/__pycache__', 'routes/__pycache__', 'utils/__pycache__']:
            if os.path.exists(cache_dir):
                shutil.rmtree(cache_dir)
        app_logger.info("✓ Python cache cleared")
    except Exception as e:
        app_logger.warning(f"Could not clear cache: {e}")

    # Display startup banner
    print("\n" + "=" * 60)
    print("🎖️  INDIAN ARMY FACE ATTENDANCE SYSTEM")
    print("=" * 60)
    print(f"✓ Server starting on http://0.0.0.0:5000")
    print(f"✓ Also accessible on http://192.168.1.9:5000")
    print(f"✓ Environment: {'Development' if Config.DEBUG else 'Production'}")
    print(f"✓ Database: {Config.DB_NAME}")
    print(f"✓ Cache Control: ENABLED (Browser will always load fresh code)")
    print("=" * 60)
    print("\n🎥 CAMERA CONFIGURATION:")
    if Config.USE_IP_CAMERA:
        print(f"   → Network Camera: {Config.CAMERA_URL} (PRIORITIZED)")
        print(f"   → Fallback: System webcam (index {Config.DEFAULT_CAMERA_INDEX})")
    else:
        print(f"   → System webcam (index {Config.DEFAULT_CAMERA_INDEX})")
        print("   → Network camera: Not configured")
    print("\n⚠️  DEFAULT LOGIN CREDENTIALS:")
    print("   Username: admin")
    print("   Password: Admin@123")
    print("\n⚠️  SECURITY WARNING:")
    print("   → Change password immediately after first login")
    print("   → This is a development server - use production WSGI for deployment")
    print("\n💡 TIPS:")
    print("   → Use Ctrl+Shift+R to hard refresh browser")
    print("   → Server auto-reloads on code changes")
    print("   → Check logs/app.log for detailed logs")
    print("\n=" * 60)
    print("Press CTRL+C to quit\n")

    # Run Flask development server
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=Config.DEBUG,
        threaded=True,
        use_reloader=True,  # Auto-reload on file changes
        extra_files=[  # Watch these files for changes
            'config.py',
            'models/face_recognition.py',
            'routes/registration.py',
            'routes/attendance.py',
            'routes/auth.py',
            'routes/reports.py',
            'routes/camera.py',
            'utils/camera.py'
        ]
    )