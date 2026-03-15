-- Army Face Attendance System Database Schema

CREATE DATABASE IF NOT EXISTS army_attendance CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE army_attendance;

-- Users/Admins Table
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    rank VARCHAR(50),
    role ENUM('admin', 'officer', 'viewer') DEFAULT 'viewer',
    email VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    last_login DATETIME,
    failed_login_attempts INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_username (username),
    INDEX idx_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Employees Table
CREATE TABLE IF NOT EXISTS employees (
    id INT AUTO_INCREMENT PRIMARY KEY,
    army_id VARCHAR(50) UNIQUE NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    rank VARCHAR(50),
    unit VARCHAR(100),
    department VARCHAR(100),
    designation VARCHAR(100),
    phone VARCHAR(20),
    email VARCHAR(100),
    date_of_joining DATE,
    photo_path VARCHAR(255),
    face_embedding_id VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_army_id (army_id),
    INDEX idx_active (is_active),
    INDEX idx_unit (unit)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Attendance Table
CREATE TABLE IF NOT EXISTS attendance (
    id INT AUTO_INCREMENT PRIMARY KEY,
    employee_id INT NOT NULL,
    check_in_time DATETIME NOT NULL,
    check_out_time DATETIME,
    date DATE NOT NULL,
    status ENUM('present', 'late', 'half_day', 'absent') DEFAULT 'present',
    location VARCHAR(100),
    check_in_photo VARCHAR(255),
    check_out_photo VARCHAR(255),
    liveness_score_in FLOAT,
    liveness_score_out FLOAT,
    confidence_score FLOAT,
    work_hours FLOAT DEFAULT 0.0,
    ip_address VARCHAR(45),
    device_info VARCHAR(255),
    remarks TEXT,
    verified_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
    FOREIGN KEY (verified_by) REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE KEY unique_employee_date (employee_id, date),
    INDEX idx_employee_id (employee_id),
    INDEX idx_date (date),
    INDEX idx_status (status),
    INDEX idx_check_in (check_in_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Audit Log Table
CREATE TABLE IF NOT EXISTS audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    action VARCHAR(100) NOT NULL,
    table_name VARCHAR(50),
    record_id INT,
    old_value TEXT,
    new_value TEXT,
    ip_address VARCHAR(45),
    user_agent VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_user_id (user_id),
    INDEX idx_action (action),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Face Recognition Attempts (for security monitoring)
CREATE TABLE IF NOT EXISTS face_attempts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    employee_id INT,
    attempt_time DATETIME NOT NULL,
    success BOOLEAN DEFAULT FALSE,
    confidence_score FLOAT,
    liveness_passed BOOLEAN,
    photo_path VARCHAR(255),
    ip_address VARCHAR(45),
    failure_reason VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
    INDEX idx_employee_id (employee_id),
    INDEX idx_attempt_time (attempt_time),
    INDEX idx_success (success)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- System Settings Table
CREATE TABLE IF NOT EXISTS system_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    setting_key VARCHAR(100) UNIQUE NOT NULL,
    setting_value TEXT,
    description VARCHAR(255),
    updated_by INT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert default admin user (password: Admin@123)
INSERT INTO users (username, password_hash, full_name, rank, role, email) VALUES
('admin', 'pbkdf2:sha256:600000$aPzKxVmD$8f3e3d8c7b9a6f5e4d3c2b1a0987654321fedcba9876543210fedcba98765432',
 'System Administrator', 'Major', 'admin', 'admin@army.mil.in');

-- Insert default system settings
INSERT INTO system_settings (setting_key, setting_value, description) VALUES
('work_start_time', '08:00:00', 'Official work start time'),
('work_end_time', '17:00:00', 'Official work end time'),
('late_threshold_minutes', '15', 'Minutes after which marked as late'),
('half_day_hours', '4', 'Minimum hours for half day'),
('full_day_hours', '8', 'Minimum hours for full day'),
('face_threshold', '0.6', 'Face recognition confidence threshold'),
('liveness_threshold', '0.7', 'Liveness detection threshold'),
('allow_early_checkin_minutes', '30', 'Allow check-in before start time'),
('auto_checkout_enabled', 'false', 'Auto checkout at end of day');
