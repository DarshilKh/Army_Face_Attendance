"""
Army Face Attendance System - Configuration
विन्यास / Configuration Settings
Version: 2.0
"""

import os
from dotenv import load_dotenv
from urllib.parse import quote_plus

load_dotenv()


class Config:
    """Main configuration class"""

    # ==================== FLASK CONFIG ====================
    SECRET_KEY = os.getenv('SECRET_KEY', 'army-attendance-secret-key-2026-production')
    FLASK_ENV = os.getenv('FLASK_ENV', 'production')
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

    # ==================== DATABASE CONFIG ====================
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 3306))
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_NAME = os.getenv('DB_NAME', 'army_attendance')

    # URL-encode password for special characters
    encoded_password = quote_plus(DB_PASSWORD) if DB_PASSWORD else ''

    # MySQL connection string
    SQLALCHEMY_DATABASE_URI = f'mysql+pymysql://{DB_USER}:{encoded_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,  # Verify connections before using
        'pool_recycle': 300,  # Recycle connections after 5 minutes
        'pool_size': 10,  # Connection pool size
        'max_overflow': 20,  # Extra connections if needed
        'pool_timeout': 30,  # Timeout for getting connection
        'connect_args': {
            'connect_timeout': 10,  # MySQL connection timeout
            'charset': 'utf8mb4'
        }
    }

    # ==================== UPLOAD CONFIG ====================
    UPLOAD_FOLDER = 'static/uploads/employees'
    ATTENDANCE_PHOTOS = 'static/uploads/attendance'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp'}

    # ==================== FACE RECOGNITION CONFIG ====================
    # Threshold for face matching (lower = stricter)
    FACE_THRESHOLD = float(os.getenv('FACE_THRESHOLD', '0.4'))

    # Minimum face size in pixels
    MIN_FACE_SIZE = int(os.getenv('MIN_FACE_SIZE', '40'))

    # Face quality minimum score
    MIN_FACE_QUALITY = float(os.getenv('MIN_FACE_QUALITY', '0.35'))

    # Liveness detection
    LIVENESS_REQUIRED = os.getenv('LIVENESS_REQUIRED', 'True').lower() == 'true'
    LIVENESS_THRESHOLD = float(os.getenv('LIVENESS_THRESHOLD', '0.5'))

    # InsightFace model configuration
    INSIGHTFACE_MODEL = os.getenv('INSIGHTFACE_MODEL', 'buffalo_sc')  # Best for CPU
    DETECTION_SIZE = tuple(map(int, os.getenv('DETECTION_SIZE', '640,640').split(',')))

    # Multi-angle registration
    MULTI_ANGLE_REGISTRATION = os.getenv('MULTI_ANGLE_REGISTRATION', 'True').lower() == 'true'
    REQUIRED_ANGLES = ['front', 'left', 'right']  # Required photo angles

    # ==================== CAMERA CONFIG ====================
    # Default camera index (0 = built-in webcam, used as fallback)
    DEFAULT_CAMERA_INDEX = int(os.getenv('DEFAULT_CAMERA_INDEX', '0'))

    # Camera resolution
    CAMERA_WIDTH = int(os.getenv('CAMERA_WIDTH', '1280'))
    CAMERA_HEIGHT = int(os.getenv('CAMERA_HEIGHT', '720'))
    CAMERA_RESOLUTION = (CAMERA_WIDTH, CAMERA_HEIGHT)

    # Network Camera Configuration (prioritized over system webcam)
    CAMERA_URL = os.getenv('CAMERA_URL', '')  # e.g., "http://192.168.1.65/"
    CAMERA_USERNAME = os.getenv('CAMERA_USERNAME', '')
    CAMERA_PASSWORD = os.getenv('CAMERA_PASSWORD', '')

    # Use network camera if URL is provided, otherwise fallback to webcam
    USE_IP_CAMERA = bool(CAMERA_URL)

    # Frame rate for video processing
    CAMERA_FPS = int(os.getenv('CAMERA_FPS', '30'))

    # Live monitoring settings
    LIVE_MONITORING_ENABLED = os.getenv('LIVE_MONITORING_ENABLED', 'True').lower() == 'true'
    LIVE_MONITORING_INTERVAL = int(os.getenv('LIVE_MONITORING_INTERVAL', '2'))  # seconds
    AUTO_ATTENDANCE = os.getenv('AUTO_ATTENDANCE', 'True').lower() == 'true'

    # ==================== ATTENDANCE CONFIG ====================
    # Work timing
    WORK_START_TIME = os.getenv('WORK_START_TIME', '08:00:00')
    WORK_END_TIME = os.getenv('WORK_END_TIME', '17:00:00')

    # Late threshold (minutes after work start time)
    LATE_THRESHOLD_MINUTES = int(os.getenv('LATE_THRESHOLD_MINUTES', '15'))

    # Half day hours
    HALF_DAY_HOURS = float(os.getenv('HALF_DAY_HOURS', '4.0'))

    # Full day hours
    FULL_DAY_HOURS = float(os.getenv('FULL_DAY_HOURS', '8.0'))

    # Auto check-out time (if not manually checked out)
    AUTO_CHECKOUT_TIME = os.getenv('AUTO_CHECKOUT_TIME', '18:00:00')
    AUTO_CHECKOUT_ENABLED = os.getenv('AUTO_CHECKOUT_ENABLED', 'False').lower() == 'true'

    # ==================== SECURITY CONFIG ====================
    SESSION_TIMEOUT = int(os.getenv('SESSION_TIMEOUT', '1800'))  # 30 minutes
    MAX_LOGIN_ATTEMPTS = int(os.getenv('MAX_LOGIN_ATTEMPTS', '3'))
    PERMANENT_SESSION_LIFETIME = SESSION_TIMEOUT

    # Password requirements
    MIN_PASSWORD_LENGTH = int(os.getenv('MIN_PASSWORD_LENGTH', '8'))
    REQUIRE_SPECIAL_CHAR = os.getenv('REQUIRE_SPECIAL_CHAR', 'True').lower() == 'true'

    # ==================== LOGGING CONFIG ====================
    LOG_FOLDER = 'logs'
    LOG_FILE = os.path.join(LOG_FOLDER, 'app.log')
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 5

    # ==================== NOTIFICATION CONFIG ====================
    # Email notifications (future feature)
    ENABLE_EMAIL_NOTIFICATIONS = os.getenv('ENABLE_EMAIL_NOTIFICATIONS', 'False').lower() == 'true'
    SMTP_SERVER = os.getenv('SMTP_SERVER', '')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')

    # SMS notifications (future feature)
    ENABLE_SMS_NOTIFICATIONS = os.getenv('ENABLE_SMS_NOTIFICATIONS', 'False').lower() == 'true'

    # ==================== UI CONFIG ====================
    # Language preference
    DEFAULT_LANGUAGE = os.getenv('DEFAULT_LANGUAGE', 'hi-en')  # Hindi-English bilingual

    # Theme
    THEME = os.getenv('THEME', 'army-green')

    # Pagination
    ITEMS_PER_PAGE = int(os.getenv('ITEMS_PER_PAGE', '25'))

    # ==================== REPORT CONFIG ====================
    REPORT_LOGO = 'static/images/army_logo.png'
    REPORT_HEADER = 'भारतीय सेना उपस्थिति प्रणाली / Indian Army Attendance System'

    # ==================== BACKUP CONFIG ====================
    AUTO_BACKUP_ENABLED = os.getenv('AUTO_BACKUP_ENABLED', 'True').lower() == 'true'
    BACKUP_FOLDER = 'backups'
    BACKUP_INTERVAL_HOURS = int(os.getenv('BACKUP_INTERVAL_HOURS', '24'))
    BACKUP_RETENTION_DAYS = int(os.getenv('BACKUP_RETENTION_DAYS', '30'))

    # ==================== HELPER METHODS ====================
    @staticmethod
    def get_camera_source():
        """Get camera source (authenticated network camera URL or webcam index)"""
        if Config.USE_IP_CAMERA and Config.CAMERA_URL:
            # Build authenticated URL if credentials are provided
            if Config.CAMERA_USERNAME and Config.CAMERA_PASSWORD:
                from urllib.parse import urlparse, urlunparse
                parsed = urlparse(Config.CAMERA_URL)
                auth_url = urlunparse((
                    parsed.scheme,
                    f"{quote_plus(Config.CAMERA_USERNAME)}:{quote_plus(Config.CAMERA_PASSWORD)}@{parsed.hostname}" +
                    (f":{parsed.port}" if parsed.port else ""),
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment
                ))
                return auth_url
            return Config.CAMERA_URL
        return Config.DEFAULT_CAMERA_INDEX

    @staticmethod
    def init_folders():
        """Create necessary folders if they don't exist"""
        folders = [
            Config.UPLOAD_FOLDER,
            Config.ATTENDANCE_PHOTOS,
            Config.LOG_FOLDER,
            Config.BACKUP_FOLDER,
            'face_embeddings',
            'static/images',
            'temp'
        ]
        for folder in folders:
            os.makedirs(folder, exist_ok=True)


# Initialize folders on import
Config.init_folders()

# Debug function
if __name__ == '__main__':
    print("=" * 70)
    print("ARMY ATTENDANCE SYSTEM - CONFIGURATION")
    print("सेना उपस्थिति प्रणाली - विन्यास")
    print("=" * 70)
    print(f"\n📁 Database:")
    print(f"   Host: {Config.DB_HOST}:{Config.DB_PORT}")
    print(f"   User: {Config.DB_USER}")
    print(f"   Database: {Config.DB_NAME}")
    print(f"   URI: {Config.SQLALCHEMY_DATABASE_URI[:50]}...")

    print(f"\n📸 Face Recognition:")
    print(f"   Model: {Config.INSIGHTFACE_MODEL}")
    print(f"   Threshold: {Config.FACE_THRESHOLD}")
    print(f"   Min Face Size: {Config.MIN_FACE_SIZE}px")
    print(f"   Detection Size: {Config.DETECTION_SIZE}")
    print(f"   Liveness Required: {Config.LIVENESS_REQUIRED}")

    print(f"\n🎥 Camera:")
    print(f"   Source: {Config.get_camera_source()}")
    print(f"   Resolution: {Config.CAMERA_WIDTH}x{Config.CAMERA_HEIGHT}")
    print(f"   FPS: {Config.CAMERA_FPS}")
    print(f"   Live Monitoring: {Config.LIVE_MONITORING_ENABLED}")

    print(f"\n⏰ Attendance:")
    print(f"   Work Hours: {Config.WORK_START_TIME} - {Config.WORK_END_TIME}")
    print(f"   Late Threshold: {Config.LATE_THRESHOLD_MINUTES} minutes")
    print(f"   Full Day Hours: {Config.FULL_DAY_HOURS}")

    print(f"\n🔐 Security:")
    print(f"   Session Timeout: {Config.SESSION_TIMEOUT} seconds")
    print(f"   Max Login Attempts: {Config.MAX_LOGIN_ATTEMPTS}")

    print("\n" + "=" * 70)
