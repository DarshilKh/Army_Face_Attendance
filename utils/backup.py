"""
Database backup utilities — plain mysqldump against the same MySQL
instance the app itself connects to (config.py's DB_* values), used by
both the "Backup Database Now" Settings button and the periodic
auto-backup sweep in app.py's maintenance thread.
"""
import os
import subprocess
from datetime import datetime, timedelta
from typing import Optional, Tuple

from config import Config
from utils.logger import app_logger

MYSQLDUMP_TIMEOUT_SECONDS = 300


def run_database_backup() -> Tuple[bool, str]:
    """
    Dump the live database to a timestamped .sql file in Config.BACKUP_FOLDER.
    Returns (success, path-on-success or error-message-on-failure).
    """
    os.makedirs(Config.BACKUP_FOLDER, exist_ok=True)
    filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    path = os.path.join(Config.BACKUP_FOLDER, filename)

    cmd = [
        'mysqldump',
        '-h', Config.DB_HOST,
        '-P', str(Config.DB_PORT),
        '-u', Config.DB_USER,
        Config.DB_NAME,
    ]

    # Password passed via env var (MYSQL_PWD), not argv, so it never shows
    # up in a process listing.
    env = os.environ.copy()
    if Config.DB_PASSWORD:
        env['MYSQL_PWD'] = Config.DB_PASSWORD

    try:
        with open(path, 'wb') as out:
            result = subprocess.run(
                cmd, stdout=out, stderr=subprocess.PIPE, env=env,
                timeout=MYSQLDUMP_TIMEOUT_SECONDS
            )

        if result.returncode != 0:
            os.remove(path)
            err = result.stderr.decode(errors='replace').strip()[:300]
            app_logger.error(f"Database backup failed: {err}")
            return False, err or 'mysqldump exited with an error'

        app_logger.info(f"Database backup created: {path}")
        return True, path

    except FileNotFoundError:
        return False, 'mysqldump not found on PATH'
    except subprocess.TimeoutExpired:
        if os.path.exists(path):
            os.remove(path)
        return False, 'Backup timed out'
    except Exception as e:
        if os.path.exists(path):
            os.remove(path)
        app_logger.error(f"Database backup error: {e}")
        return False, str(e)


def _backup_files():
    if not os.path.isdir(Config.BACKUP_FOLDER):
        return []
    return [
        f for f in os.listdir(Config.BACKUP_FOLDER)
        if f.startswith('backup_') and f.endswith('.sql')
    ]


def prune_old_backups() -> int:
    """Delete backup files older than Config.BACKUP_RETENTION_DAYS. Returns count removed."""
    cutoff = datetime.now() - timedelta(days=Config.BACKUP_RETENTION_DAYS)
    removed = 0
    for fname in _backup_files():
        fpath = os.path.join(Config.BACKUP_FOLDER, fname)
        try:
            if datetime.fromtimestamp(os.path.getmtime(fpath)) < cutoff:
                os.remove(fpath)
                removed += 1
        except OSError:
            continue

    if removed:
        app_logger.info(f"Pruned {removed} backup(s) older than {Config.BACKUP_RETENTION_DAYS} days")
    return removed


def last_backup_age_hours() -> Optional[float]:
    """Hours since the most recent backup file, or None if no backups exist yet."""
    files = _backup_files()
    if not files:
        return None

    newest = max(os.path.getmtime(os.path.join(Config.BACKUP_FOLDER, f)) for f in files)
    return (datetime.now().timestamp() - newest) / 3600
