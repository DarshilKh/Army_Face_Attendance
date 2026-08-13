import logging
import os
from datetime import datetime
import sys

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# Create logger
app_logger = logging.getLogger('ArmyAttendance')
app_logger.setLevel(logging.INFO)


def set_log_level(level_name):
    """Apply a log level (e.g. 'DEBUG', 'WARNING') to the logger and all its
    handlers at runtime — called from Settings so changes take effect live."""
    level = getattr(logging, str(level_name).upper(), None)
    if not isinstance(level, int):
        app_logger.warning(f"Invalid log level '{level_name}', ignoring")
        return
    app_logger.setLevel(level)
    for handler in app_logger.handlers:
        handler.setLevel(level)


# Clear existing handlers
app_logger.handlers.clear()

# File handler (UTF-8 encoding for Unicode support)
log_filename = f"logs/app_{datetime.now().strftime('%Y%m%d')}.log"
file_handler = logging.FileHandler(log_filename, encoding='utf-8')
file_handler.setLevel(logging.INFO)

# Console handler (UTF-8 encoding for Windows)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

# Set UTF-8 encoding for console on Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# Formatter (without special Unicode characters for compatibility)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add handlers
app_logger.addHandler(file_handler)
app_logger.addHandler(console_handler)

# Prevent propagation to root logger
app_logger.propagate = False

# Test logger
if __name__ == '__main__':
    app_logger.info("Logger initialized successfully")
    app_logger.debug("Debug message")
    app_logger.warning("Warning message")
    app_logger.error("Error message")