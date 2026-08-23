-- Migration: multi-camera support + late_minutes tracking
-- Run this by hand against your existing army_attendance database:
--   mysql -u root -p army_attendance < database/migrate_multicam.sql
-- Safe to re-run: uses IF NOT EXISTS / conditional column add.

USE army_attendance;

CREATE TABLE IF NOT EXISTS cameras (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    location VARCHAR(100),
    camera_type ENUM('webcam', 'ip') NOT NULL DEFAULT 'webcam',
    url VARCHAR(255),
    username VARCHAR(100),
    password VARCHAR(100),
    width INT DEFAULT 1280,
    height INT DEFAULT 720,
    fps INT DEFAULT 15,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Seed a webcam entry only if the table is empty (first run of this migration)
INSERT INTO cameras (name, location, camera_type, is_active)
SELECT 'System Webcam', 'Default', 'webcam', TRUE
WHERE NOT EXISTS (SELECT 1 FROM cameras);

-- If you already had a network camera configured via .env (CAMERA_URL), add it
-- as a row too so it shows up in the new Cameras admin UI. Edit the values below
-- to match your .env before running, or just add it later from Settings > Cameras.
-- INSERT INTO cameras (name, location, camera_type, url, username, password, is_active)
-- VALUES ('Main Gate', 'Main Gate', 'ip', 'rtsp://192.168.1.188:554/stream0', '', '', TRUE);

-- Add late_minutes to attendance if it doesn't already exist
SET @col_exists = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'army_attendance'
      AND TABLE_NAME = 'attendance'
      AND COLUMN_NAME = 'late_minutes'
);

SET @ddl = IF(@col_exists = 0,
    'ALTER TABLE attendance ADD COLUMN late_minutes INT AFTER confidence_score',
    'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
