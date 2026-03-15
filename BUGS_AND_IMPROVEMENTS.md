# 🐛 Bugs & 🚀 Improvements Report

**Army Face Attendance System — Full Code Audit**
*Generated: 2026-03-15*

---

## Table of Contents

1. [🔴 Critical Bugs](#-critical-bugs)
2. [🟠 Major Bugs](#-major-bugs)
3. [🟡 Minor Bugs](#-minor-bugs)
4. [🔒 Security Vulnerabilities](#-security-vulnerabilities)
5. [⚡ Performance Issues](#-performance-issues)
6. [🏗️ Architectural Improvements](#-architectural-improvements)
7. [✨ Feature & Quality Improvements](#-feature--quality-improvements)

---

## 🔴 Critical Bugs

### 1. SQL Injection in Search Queries
**Files:** `routes/attendance.py` (L780-784), `routes/registration.py` (L397-403)

The `search` parameter is interpolated directly into SQL `LIKE` clauses using f-strings, making the app **vulnerable to SQL injection**.

```python
# VULNERABLE CODE (attendance.py L780-784)
query = query.filter(
    db.or_(
        Employee.army_id.like(f'%{search}%'),
        Employee.full_name.like(f'%{search}%')
    )
)
```

**Fix:** While SQLAlchemy's `.like()` is *parameterized* for the value itself, the `%` wildcards should still be properly escaped. More importantly, `LIKE` pattern characters (`%`, `_`) in user input should be escaped to prevent unexpected pattern matching:

```python
from sqlalchemy import func
escaped_search = search.replace('%', '\\%').replace('_', '\\_')
query = query.filter(
    db.or_(
        Employee.army_id.like(f'%{escaped_search}%', escape='\\'),
        Employee.full_name.like(f'%{escaped_search}%', escape='\\')
    )
)
```

---

### 2. Deprecated `db.session.execute('SELECT 1')` — Raw String Query
**File:** `routes/attendance.py` (L929)

```python
db.session.execute('SELECT 1')
```

SQLAlchemy 2.0 requires `text()` wrapping for raw SQL strings. This will **crash** on modern SQLAlchemy versions.

**Fix:**
```python
from sqlalchemy import text
db.session.execute(text('SELECT 1'))
```

---

### 3. `Attendance.work_hours` Column Referenced but Never Defined
**File:** `models/database.py`, `routes/attendance.py` (L191, L595, L882)

The code reads and writes `attendance.work_hours` and `attendance_record.work_hours`, but the `Attendance` model has **no `work_hours` column defined**. This will raise `AttributeError` at runtime during checkout.

**Fix:** Add to the `Attendance` model:
```python
work_hours = db.Column(db.Float, default=0.0)
```

---

### 4. Hardcoded Liveness Score (Never Actually Computed)
**File:** `routes/attendance.py` (L674)

```python
liveness_score_in=0.85,  # Default (can be enhanced with actual liveness)
```

Despite having a full `LivenessDetector` class in `utils/liveness_detection.py`, liveness detection is **never actually called** during attendance marking. The `LIVENESS_REQUIRED` config flag is ignored. This means the anti-spoofing system is entirely non-functional.

---

### 5. `.env` File Committed with Real Credentials
**File:** `.env`

The `.env` file contains:
- Database password: `123@`
- Camera credentials: `admin / admin123`
- Secret key placeholder text

While `.env` is in `.gitignore`, it's currently trackable. The `.gitignore` lists `.env` **twice** (line 2 and 5), suggesting confusion about whether it's tracked.

---

### 6. Reports Blueprint References Non-Existent Templates
**File:** `routes/reports.py` (L48, L102, L158, L203)

The reports route renders templates like `reports/index.html`, `reports/daily.html`, `reports/monthly.html`, `reports/employee.html`, but the `templates/` directory has only `reports.html` at the root level — **no `reports/` subdirectory exists**. These endpoints will crash with `TemplateNotFound`.

---

## 🟠 Major Bugs

### 7. Inconsistent Password Between `app.py` and `generate_admin.py`
**Files:** `app.py` (L213, L301), `generate_admin.py` (L5)

- `app.py` CLI `create_admin` uses password `Admin@123` with `method='scrypt'`
- `app.py` startup banner says password is `admin123`
- `generate_admin.py` uses password `admin123` with `method='pbkdf2:sha256'`
- `schema.sql` has a hardcoded hash for an unknown password

A new user following the banner message will fail to log in if the CLI command was used.

---

### 8. Singleton `__init__` Re-Entrance Guard is Fragile
**File:** `models/face_recognition.py` (L43-45)

```python
def __init__(self):
    if not hasattr(self, 'initialized'):
        ...
```

If `__init__` raises an exception partway through, `self.initialized` is never set, so the next attempt will partially re-initialize the singleton — potentially creating corrupt state. The guard should wrap the full init in a try/except that sets a failure flag.

---

### 9. Global Module-Level Caches Are Not Thread-Safe
**File:** `routes/attendance.py` (L42-50)

```python
last_recognized_cache = {}
employee_cache = {}
attendance_cache = {}
```

These global dictionaries are accessed concurrently from all Flask worker threads without any locking. With `threaded=True` in `app.run()`, this can cause race conditions, corrupted data, and `RuntimeError: dictionary changed size during iteration`.

**Fix:** Use `threading.Lock()` guards, or switch to a thread-safe cache like `cachetools.TTLCache`.

---

### 10. Employee Cache Holds SQLAlchemy Objects Outside Session
**File:** `routes/attendance.py` (L146)

```python
employee_cache[army_id] = (employee, current_time)
```

Cached `Employee` objects become **detached** from the SQLAlchemy session. Accessing lazy-loaded relationships (like `.attendances`) on a cached object will raise `DetachedInstanceError`. Even accessing regular attributes may fail after session recycling.

---

### 11. Face Hash Uses Only First 16 Values — Collision Risk
**File:** `models/face_recognition.py` (L456-457)

```python
return str(hash(embedding[:16].tobytes()))
```

Using only the first 16 floats of a 512-dimension embedding creates a very high probability of hash collisions between different faces, leading to **wrong person being matched from cache**.

**Fix:** Use the full embedding for hashing, or use a proper hash function:
```python
import hashlib
return hashlib.md5(embedding.tobytes()).hexdigest()
```

---

### 12. Open Redirect Vulnerability on Login
**File:** `routes/auth.py` (L65-66)

```python
next_page = request.args.get('next')
return redirect(next_page if next_page else url_for('auth.dashboard'))
```

The `next` parameter is not validated. An attacker can craft a URL like `/login?next=https://evil.com` to redirect users to a malicious site after login.

**Fix:**
```python
from urllib.parse import urlparse
next_page = request.args.get('next')
if next_page and urlparse(next_page).netloc == '':
    return redirect(next_page)
return redirect(url_for('auth.dashboard'))
```

---

### 13. Duplicate Embedding Check Has False Positive Risk
**File:** `models/face_recognition.py` (L514-519)

```python
if max_similarity > 0.75:
    return False, f"Face already registered ({max_similarity:.0%} similar)", None
```

This checks against **all** embeddings including the employee's own previous angles. If an employee registers a second angle, it may get rejected as a "duplicate" because it's similar to their first registered angle. The check should **exclude embeddings belonging to the same employee**.

---

### 14. Camera Manager Opens/Closes Camera on Every Frame
**File:** `utils/camera.py` (L210-226)

Every call to `_capture_from_system()` opens a new `VideoCapture`, reads one frame, and releases it. This is extremely slow (hundreds of milliseconds per frame) and causes visible delays and flickering when using the system webcam for streaming.

**Fix:** Keep the `VideoCapture` instance open and reuse it across frames.

---

## 🟡 Minor Bugs

### 15. `datetime.utcnow` Deprecated in Python 3.12+
**File:** `models/database.py` (L20-21, L47-48, L73-74, L89, L104, L115)

`datetime.utcnow` is deprecated since Python 3.12 and will be removed in a future Python version. Use `datetime.now(datetime.UTC)` instead.

---

### 16. Cache Busting Defeats Browser Caching Entirely
**File:** `app.py` (L67-91)

Using `int(time.time())` as the cache version **changes every second**, and the `add_no_cache_headers` handler adds aggressive no-cache headers to **all responses** including static CSS/JS/images. This eliminates any browser caching benefit and unnecessarily increases server load.

**Fix:** Use a static version number or the file's mtime for cache busting, and only disable caching for HTML/API responses, not static assets.

---

### 17. Bare `except:` Clauses Swallow All Exceptions
**Files:** `models/face_recognition.py` (L458, L763), `routes/registration.py` (L276, L302, L373), `utils/liveness_detection.py` (L91, L107), `routes/attendance.py` (L251)

Multiple `except:` clauses without specifying exception types catch everything including `SystemExit`, `KeyboardInterrupt`, and `MemoryError`. This makes debugging extremely difficult.

**Fix:** Use `except Exception:` at minimum, and log the error.

---

### 18. `app.py` Hardcodes IP Address in Banner
**File:** `app.py` (L287)

```python
print(f"✓ Also accessible on http://192.168.1.9:5000")
```

This IP is hardcoded and won't be correct on other machines.

---

### 19. `db.session.rollback()` in 500 Error Handler May Fail
**File:** `app.py` (L114)

If the 500 error was caused by a disconnected database, calling `db.session.rollback()` will raise another exception, potentially hiding the original error.

**Fix:** Wrap in try/except:
```python
try:
    db.session.rollback()
except:
    pass
```

---

### 20. `reports.py` Imports `db` from Wrong Location
**File:** `routes/reports.py` (L3)

```python
from models.database import db, Employee, Attendance, User
```

`db` is defined in `models/__init__.py`, not `models/database.py`. While this currently works due to Python's import chain, it's an incorrect and fragile import that may break with refactoring.

---

### 21. Missing `edit_employee` Route
**File:** `templates/edit_employee.html` exists (11KB) but there's no corresponding route handler in any of the route files. This template is unreachable.

---

### 22. Double `db.session.commit()` in Auth Routes
**File:** `routes/auth.py` (L47, L60)

Login success calls `db.session.commit()` twice: once to update `last_login` and once to save the `AuditLog`. While not a bug per se, it creates two unnecessary transactions. These should be combined.

---

## 🔒 Security Vulnerabilities

### 23. Weak Default `SECRET_KEY`
**File:** `config.py` (L18)

```python
SECRET_KEY = os.getenv('SECRET_KEY', 'army-attendance-secret-key-2026-production')
```

The fallback secret key is a predictable string. If `.env` doesn't set it, session cookies can be forged. The `.env` file has `SECRET_KEY=your-super-secret-key-change-this-in-production` which is equally weak.

**Fix:** Generate a proper random key and require it in production.

---

### 24. No CSRF Protection
**No file**

The app uses Flask-Login but does **not** use Flask-WTF or any CSRF protection. All POST forms (login, registration, attendance marking) are vulnerable to cross-site request forgery attacks.

**Fix:** Add `Flask-WTF` and use `csrf.init_app(app)`.

---

### 25. Health Check Endpoint Is Unauthenticated
**File:** `routes/attendance.py` (L922-923)

```python
@attendance_bp.route('/health')
def health_check():
```

The health check is accessible without login, which leaks internal system information (database status, engine version, embedding count). Add `@login_required` or restrict to internal IPs only.

---

### 26. Error Messages Leak Internal Information
**Files:** `routes/attendance.py` (L849), `routes/reports.py` (L51), `routes/registration.py` (L378)

```python
return jsonify({'success': False, 'message': str(e)}), 500
```

Stack traces and internal error details are returned directly to the client, potentially revealing database schema, file paths, and other sensitive information.

---

### 27. `generate_admin.py` Hardcodes Database Credentials
**File:** `generate_admin.py` (L24)

```python
password='123@',
```

Database credentials are hardcoded in a utility script. This file should read from `.env` or environment variables.

---

### 28. No Rate Limiting on API Endpoints
**No file**

The attendance marking endpoint (`/attendance/mark`) has no rate limiting. An attacker could flood it with requests, causing denial of service or exhausting database connections.

---

### 29. Pickle-Based Embedding Storage Is Vulnerable
**File:** `models/face_recognition.py` (L137)

```python
embeddings = pickle.load(f)
```

`pickle.load()` can execute arbitrary code if the embeddings file is tampered with. For a military system, this is a significant risk.

**Fix:** Use a safer format like JSON + numpy serialization, or sign the pickle file.

---

### 30. No Input Validation on `limit` Parameter
**File:** `routes/attendance.py` (L860)

```python
limit = int(request.args.get('limit', 10))
```

A user can set `limit=999999` to dump the entire attendance table. There's also no validation that would catch non-integer input (though `int()` would throw a 500).

---

### 31. Account Lockout Has No Time-Based Reset
**File:** `routes/auth.py` (L38)

Once `failed_login_attempts >= 3`, the account is locked permanently until an admin manually resets it. There's no automatic unlock after a time period, which could be weaponized for denial of service against any account.

---

## ⚡ Performance Issues

### 32. `stats_today()` Loads All Attendance Records Into Memory
**File:** `routes/attendance.py` (L831)

```python
today_attendance = Attendance.query.filter_by(date=today).all()
```

Uses `.all()` then iterates in Python to count statuses. Should use SQL `COUNT(*)` with `GROUP BY status`.

```python
from sqlalchemy import func
stats = db.session.query(
    Attendance.status, func.count()
).filter_by(date=today).group_by(Attendance.status).all()
```

---

### 33. Monthly Report Loads All Attendance into Python
**File:** `routes/reports.py` (L127-153)

The monthly report fetches ALL attendance records for the month, then loops through all employees in Python to compute stats. For large datasets (1000+ employees × 30 days), this is very slow.

**Fix:** Use SQL aggregation:
```sql
SELECT employee_id, COUNT(DISTINCT date) as present_days
FROM attendance WHERE date BETWEEN ? AND ?
GROUP BY employee_id
```

---

### 34. `_precompute_embeddings_array()` Called Redundantly After Delete
**File:** `models/face_recognition.py` (L596-599)

```python
saved = self._save_embeddings()      # Already calls _precompute_embeddings_array()
self._precompute_embeddings_array()  # Called AGAIN
```

`_save_embeddings()` already calls `_precompute_embeddings_array()` internally (L168), so it runs twice on every delete.

---

### 35. Image Enhancement Is Too Aggressive for Registration
**File:** `routes/registration.py` (L286-287)

`enhance_face_image()` applies CLAHE + `fastNlMeansDenoisingColored()`, and then `register_face()` applies CLAHE **again** via `_enhance_for_registration()`. Double-enhancing can distort features and degrade recognition accuracy.

---

## 🏗️ Architectural Improvements

### 36. No Database Migration Strategy
The project uses `db.create_all()` which only creates tables that don't exist — it **cannot modify** existing tables. Any schema change (like adding `work_hours`) requires manual SQL. Adopt Flask-Migrate (Alembic) for proper migrations.

---

### 37. Singleton Pattern Is Anti-Pattern for Testing
**Files:** `models/face_recognition.py`, `utils/camera.py`, `utils/liveness_detection.py`

The `face_engine`, `camera_manager`, and `liveness_detector` are all module-level singletons. This makes unit testing impossible without monkeypatching.

**Fix:** Use Flask's application context pattern or dependency injection.

---

### 38. No Unit Tests
There are **zero** test files in the project. For a face-recognition attendance system used in a military context, this is a critical gap.

---

### 39. Duplicated `decode_base64_image()` Function
**Files:** `routes/attendance.py` (L57-94), `routes/registration.py` (L30-53)

The same function is defined independently in two files with slightly different implementations. Extract to a shared utility module.

---

### 40. Config Values Are Not Used from `SystemSetting` Table
**File:** `models/database.py` (L107-116)

The `SystemSetting` model and `system_settings` table exist (with settings like `face_threshold`, `work_start_time`) but are **never queried** at runtime. All config values come exclusively from the `.env` file via `Config` class. The database settings are dead code.

---

### 41. No Request Logging Middleware or APM
While `before_request` sets `g.start_time`, there's no structured request logging with response times, status codes, and user tracking. This makes debugging production issues difficult.

---

### 42. No Graceful Shutdown for Thread Pool
**File:** `models/face_recognition.py` (L758-764)

`__del__` is unreliable in Python (may never be called). The `ThreadPoolExecutor` should be shut down via Flask's `@app.teardown_appcontext` or `atexit` hooks.

---

## ✨ Feature & Quality Improvements

### 43. Implement Actual Liveness Detection During Attendance
The `LivenessDetector` class is fully implemented but never used. Wire it into the attendance marking flow:
```python
if Config.LIVENESS_REQUIRED:
    score, details = liveness_detector.quick_liveness_check(frame)
    if score < Config.LIVENESS_THRESHOLD:
        return error_response("Liveness check failed")
```

---

### 44. Add Employee Edit/Update Functionality
`templates/edit_employee.html` exists but has no backend route. Implement `PUT /registration/employee/<id>/edit` for updating employee details and re-registering faces.

---

### 45. Add Proper Logging Rotation
**File:** `utils/logger.py`

The logger creates a new file daily (`app_YYYYMMDD.log`) but doesn't implement the `RotatingFileHandler` that `Config` references (`LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`). Old logs accumulate forever.

**Fix:** Use `RotatingFileHandler` or `TimedRotatingFileHandler`.

---

### 46. Add Backup Functionality
While `Config` has backup settings (`AUTO_BACKUP_ENABLED`, `BACKUP_FOLDER`, etc.), no backup code exists. Implement scheduled database and embeddings backups.

---

### 47. Add Email/SMS Notification System
Config has `ENABLE_EMAIL_NOTIFICATIONS` and `ENABLE_SMS_NOTIFICATIONS` flags, but these are marked as "future feature" with no implementation.

---

### 48. Add Analytics Dashboard
`templates/analytics.html` exists (3.8KB) but has no route handler. Implement data visualization for attendance trends.

---

### 49. Use WSGI Server in Production
**File:** `app.py` (L304)

The app uses Flask's built-in development server (`app.run()`) which is:
- Single-process
- Not optimized for production
- Has security warnings

**Fix:** Add `gunicorn` (Linux) or `waitress` (Windows) configuration for production deployment.

---

### 50. Add Input Sanitization for All User Inputs
Employee fields like `full_name`, `unit`, `department` are stored directly from form data without sanitization. Add HTML encoding and length validation to prevent stored XSS attacks.

---

### 51. Add Comprehensive `.gitignore`
The current `.gitignore` is minimal. Add:
```
*.pyc
*.pyo
.DS_Store
face_embeddings/
backups/
temp/
*.log
.vscode/
```

---

### 52. Add Docker/Container Support
For deployment in military environments, containerization would ensure consistent deployment across different systems.

---

## Summary Table

| Category | Count | Severity |
|---|---|---|
| 🔴 Critical Bugs | 6 | Immediate fix required |
| 🟠 Major Bugs | 8 | Should fix before deployment |
| 🟡 Minor Bugs | 8 | Fix when possible |
| 🔒 Security Vulnerabilities | 9 | Critical for military system |
| ⚡ Performance Issues | 4 | Degrades user experience |
| 🏗️ Architecture Issues | 7 | Long-term maintainability |
| ✨ Feature Improvements | 10 | Enhance system capabilities |
| **Total** | **52** | — |
