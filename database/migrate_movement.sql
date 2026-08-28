-- Migration: Person Movement (leave/holiday out-in tracking)
-- Run this by hand against your existing army_attendance database:
--   mysql -u root -p army_attendance < database/migrate_movement.sql
-- Safe to re-run: uses IF NOT EXISTS.

USE army_attendance;

CREATE TABLE IF NOT EXISTS movement_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    employee_id INT NOT NULL,
    reason VARCHAR(50) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    out_time DATETIME NOT NULL,
    out_photo VARCHAR(255),
    in_time DATETIME,
    in_photo VARCHAR(255),
    status ENUM('out', 'returned') DEFAULT 'out',
    remarks TEXT,
    verified_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
    FOREIGN KEY (verified_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_employee_id (employee_id),
    INDEX idx_status (status),
    INDEX idx_start_date (start_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
