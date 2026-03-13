# 🎖️ Indian Army Face Attendance System

A real-time face recognition–based attendance management system built for the Indian Army. The system uses **InsightFace** deep learning models and **liveness detection** to securely mark attendance via check-in/check-out, with support for network (IP) cameras and system webcams.

> **भारतीय सेना उपस्थिति प्रणाली** — Bilingual (Hindi-English) interface throughout.

---

## ✨ Features

- **Real-Time Face Recognition** — Powered by InsightFace (`buffalo_l` / `buffalo_sc`) with two-stage processing: instant face detection + async recognition for zero-lag experience.
- **Liveness Detection** — Anti-spoofing via blink detection, mouth movement analysis, texture analysis, and screen reflection checks using MediaPipe.
- **Multi-Angle Registration** — Employees are registered with front, left, and right face photos for more accurate recognition.
- **Network Camera Support** — Prioritizes IP/network cameras (with authentication) and falls back to the system webcam.
- **Attendance Management** — Automatic check-in/check-out with late, half-day, and present status classification.
- **Dashboard & Analytics** — Live stats, daily/monthly attendance summaries, and per-employee reports.
- **Report Generation** — Export attendance reports as **Excel (.xlsx)** and **PDF** with Hindi–English headers.
- **Role-Based Access Control** — Three roles: `admin`, `officer`, `viewer`.
- **Audit Logging** — Every login, logout, and password change is logged.
- **Security** — Account lockout after failed login attempts, session timeout, password strength enforcement, and security headers.

---

## 🏗️ Tech Stack

| Layer            | Technology                                                 |
| ---------------- | ---------------------------------------------------------- |
| **Backend**      | Python 3.10+, Flask 3.0                                    |
| **Database**     | MySQL 8.0+ (via PyMySQL + SQLAlchemy)                      |
| **Face AI**      | InsightFace (ONNX Runtime), MediaPipe                      |
| **Computer Vision** | OpenCV                                                  |
| **Frontend**     | Jinja2 templates, Vanilla JS, CSS                          |
| **Reports**      | ReportLab (PDF), openpyxl (Excel)                          |

---

## 📁 Project Structure

```
army_face_attendance/
│
├── app.py                  # Application entry point (Flask app factory)
├── config.py               # All configuration (DB, camera, face AI, etc.)
├── generate_admin.py       # Standalone script to create/reset admin user
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (not committed to Git)
├── .gitignore
│
├── database/
│   └── schema.sql          # Full MySQL schema (tables + seed data)
│
├── models/
│   ├── __init__.py          # SQLAlchemy & Flask-Login initialization
│   ├── database.py          # ORM models (User, Employee, Attendance, etc.)
│   └── face_recognition.py  # FaceRecognitionEngine singleton (InsightFace)
│
├── routes/
│   ├── __init__.py          # Blueprint registration
│   ├── auth.py              # Login, logout, dashboard, settings, password
│   ├── attendance.py        # Mark attendance, view records, stats API
│   ├── registration.py      # Employee CRUD, multi-angle photo capture
│   ├── reports.py           # Daily/monthly/employee reports, Excel export
│   └── camera.py            # Camera status, MJPEG stream, snapshot API
│
├── utils/
│   ├── camera.py            # CameraManager (network + webcam fallback)
│   ├── liveness_detection.py# LivenessDetector (blink, texture, reflection)
│   ├── image_processing.py  # Image preprocessing, enhancement, alignment
│   └── logger.py            # Application logger setup
│
├── templates/               # Jinja2 HTML templates
│   ├── base.html            # Base layout
│   ├── login.html
│   ├── dashboard.html
│   ├── mark_attendance.html
│   ├── registration.html
│   ├── manage_employees.html
│   ├── reports.html
│   └── ...                  # (15 templates total)
│
├── static/
│   ├── css/style.css        # Main stylesheet
│   ├── js/
│   │   ├── main.js          # Common utilities
│   │   ├── camera.js        # Frontend camera handling
│   │   └── liveness.js      # Frontend liveness prompts
│   ├── images/              # Static assets (logos, etc.)
│   └── uploads/             # Employee photos & attendance snapshots
│
├── face_embeddings/         # Serialized face embedding data (pickle)
├── logs/                    # Application log files
├── backups/                 # Database backup files
└── temp/                    # Temporary processing files
```

---

## ⚙️ Prerequisites

Before setting up the project, ensure the following are installed on your system:

1. **Python 3.10+** — [Download](https://www.python.org/downloads/)
2. **MySQL 8.0+** — [Download](https://dev.mysql.com/downloads/mysql/)
3. **Microsoft Visual C++ Build Tools** — Required by some packages like `insightface` on Windows.
   - Download from [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/).
4. **Git** (optional) — For cloning the repository.
5. **Webcam or Network Camera** — At least one camera source is needed for face recognition.

---

## 🚀 Setup & Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd army_face_attendance
```

### 2. Create & Activate a Virtual Environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

> **Note:** On Windows, `insightface` and `onnxruntime` may need pre-built wheels. If installation fails, try:
> ```bash
> pip install onnxruntime
> pip install insightface --no-deps
> pip install -r requirements.txt
> ```

### 4. Set Up MySQL Database

1. Open MySQL shell or a GUI client (e.g., MySQL Workbench, HeidiSQL).
2. Run the schema file to create the database and tables:

```sql
source database/schema.sql;
```

Or manually:

```sql
CREATE DATABASE IF NOT EXISTS army_attendance
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

The application will also auto-create tables on first run using SQLAlchemy.

### 5. Configure Environment Variables

Create a `.env` file in the project root (or edit the existing one):

```env
# ─── Database ────────────────────────────────
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=army_attendance

# ─── Flask ───────────────────────────────────
SECRET_KEY=your-super-secret-key-change-this
FLASK_ENV=development
DEBUG=True

# ─── Network Camera (optional) ──────────────
CAMERA_URL=http://192.168.1.65/
CAMERA_USERNAME=admin
CAMERA_PASSWORD=admin123

# ─── Face Recognition ───────────────────────
FACE_THRESHOLD=0.3
MIN_FACE_SIZE=80
MIN_FACE_QUALITY=0.50
INSIGHTFACE_MODEL=buffalo_l
DETECTION_SIZE=800,800
LIVENESS_REQUIRED=True
LIVENESS_THRESHOLD=0.7

# ─── Security ───────────────────────────────
SESSION_TIMEOUT=1800
MAX_LOGIN_ATTEMPTS=3
```

> **Important:** Change `SECRET_KEY` and `DB_PASSWORD` before deploying to production.

### 6. Create the Admin User

Run the admin generator script to seed the first admin account:

```bash
python generate_admin.py
```

Or use the Flask CLI command:

```bash
flask create-admin
```

**Default credentials:**

| Field    | Value      |
| -------- | ---------- |
| Username | `admin`    |
| Password | `admin123` |

> ⚠️ **Change the default password immediately after first login.**

### 7. Run the Application

```bash
python app.py
```

The server will start on:

- **Local:** http://localhost:5000
- **Network:** http://0.0.0.0:5000 (accessible from other devices on the LAN)

---

## 📖 Usage Guide

### Logging In

1. Open http://localhost:5000 in your browser.
2. Enter the admin credentials.
3. You will be redirected to the **Dashboard**.

### Registering Employees

1. Navigate to **Registration** from the sidebar.
2. Fill in employee details (Army ID, Name, Rank, Unit, etc.).
3. Capture or upload **three face photos** (front, left profile, right profile).
4. Submit the form — the system will extract and store face embeddings.

### Marking Attendance

1. Go to **Mark Attendance**.
2. Position the employee in front of the camera.
3. The system detects and recognizes the face in real time.
4. If recognized with sufficient confidence and liveness check passes, attendance is marked automatically.
5. Check-out works the same way — the system detects prior check-in for the day.

### Viewing Reports

1. Navigate to **Reports**.
2. Choose between Daily, Monthly, or Individual Employee reports.
3. Export to **Excel** for further analysis.

---

## 🎥 Camera Configuration

The system supports two camera sources with automatic fallback:

| Priority | Source            | Config Key                        |
| -------- | ----------------- | --------------------------------- |
| 1        | Network IP Camera | `CAMERA_URL`, `CAMERA_USERNAME`, `CAMERA_PASSWORD` |
| 2        | System Webcam     | `DEFAULT_CAMERA_INDEX` (default: `0`)               |

- If a `CAMERA_URL` is set in `.env`, the network camera is tried first.
- On failure, the system automatically falls back to the system webcam.
- Use the `/api/camera/status` endpoint to check the active camera source.
- Use the `/api/camera/reset` endpoint (POST) to force a camera re-check.

---

## 🔧 Flask CLI Commands

The application registers several CLI commands:

```bash
# Initialize database tables
flask init-db

# Create default admin user
flask create-admin

# Reset all face embeddings
flask reset-embeddings

# Clear Python cache files
flask clear-cache
```

---

## 🛡️ Security Notes

- **Account Lockout:** After 3 failed login attempts, the account is locked.
- **Session Timeout:** Sessions expire after 30 minutes of inactivity (configurable via `SESSION_TIMEOUT`).
- **Password Policy:** Minimum 8 characters, must include uppercase, lowercase, and numbers.
- **Liveness Detection:** Prevents photo/screen-based spoofing attacks.
- **Security Headers:** `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection` are set on all responses.
- **Audit Logs:** All login/logout/password-change events are recorded in the `audit_logs` table.

---

## 🗄️ Database Schema

The MySQL database (`army_attendance`) contains the following tables:

| Table              | Purpose                                      |
| ------------------ | -------------------------------------------- |
| `users`            | Admin/officer/viewer accounts                |
| `employees`        | Registered personnel (Army ID, rank, unit)   |
| `attendance`       | Daily check-in/out records with photos       |
| `audit_logs`       | Security audit trail                         |
| `face_attempts`    | Face recognition attempt logging             |
| `system_settings`  | Configurable system parameters               |

See [`database/schema.sql`](database/schema.sql) for the full schema.

---

## 🐛 Troubleshooting

| Issue | Solution |
| ----- | -------- |
| `ModuleNotFoundError: insightface` | Ensure you installed all dependencies: `pip install -r requirements.txt`. On Windows, you may need Visual C++ Build Tools. |
| MySQL connection refused | Verify MySQL is running and `.env` credentials are correct. |
| Camera not detected | Check `CAMERA_URL` in `.env`, or ensure a webcam is connected. Visit `/api/camera/status` to diagnose. |
| Face not recognized | Ensure the employee is registered with good quality photos. Lower `FACE_THRESHOLD` for less strict matching. |
| `onnxruntime` errors | Try installing a specific version: `pip install onnxruntime==1.16.3`. GPU users can try `onnxruntime-gpu`. |
| Slow face recognition | Use `buffalo_sc` model instead of `buffalo_l` (set `INSIGHTFACE_MODEL=buffalo_sc` in `.env`). Reduce `DETECTION_SIZE` to `640,640`. |
| Browser shows stale pages | Press `Ctrl + Shift + R` for a hard refresh. The server has cache busting enabled. |

---

## 🚀 Production Deployment

For production use, **do not** use the Flask development server. Instead:

1. **Set environment variables:**
   ```env
   FLASK_ENV=production
   DEBUG=False
   SECRET_KEY=<a-strong-random-secret>
   ```

2. **Use a production WSGI server** (e.g., Gunicorn or Waitress):
   ```bash
   # Linux (Gunicorn)
   pip install gunicorn
   gunicorn -w 4 -b 0.0.0.0:5000 app:app

   # Windows (Waitress)
   pip install waitress
   waitress-serve --port=5000 app:app
   ```

3. **Use a reverse proxy** (Nginx or Apache) in front of the WSGI server for HTTPS and static file serving.

---

## 📝 License

This project is intended for internal use by the Indian Army. All rights reserved.

---

## 🤝 Contributing

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-feature`.
3. Commit changes: `git commit -m "Add my feature"`.
4. Push to branch: `git push origin feature/my-feature`.
5. Open a Pull Request.

---

<p align="center">
  <b>🎖️ Jai Hind! 🇮🇳</b><br>
  <i>Built for the Indian Army — भारतीय सेना के लिए निर्मित</i>
</p>
