import sqlite3
from contextlib import contextmanager
from typing import Generator

from flask import current_app


@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    connection = sqlite3.connect(current_app.config["DATABASE"])
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db(database_path: str) -> None:
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
                student_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                usn TEXT COLLATE NOCASE UNIQUE NOT NULL,
                email TEXT COLLATE NOCASE UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_preferences (
                student_id INTEGER PRIMARY KEY,
                attendance_enabled INTEGER NOT NULL DEFAULT 0
                    CHECK (attendance_enabled IN (0, 1)),
                attendance_time TEXT NOT NULL DEFAULT '07:00'
                    CHECK (
                        length(attendance_time) = 5
                        AND attendance_time GLOB '[0-2][0-9]:[0-5][0-9]'
                        AND attendance_time <= '23:59'
                    ),
                task_enabled INTEGER NOT NULL DEFAULT 0
                    CHECK (task_enabled IN (0, 1)),
                task_time TEXT NOT NULL DEFAULT '08:00'
                    CHECK (
                        length(task_time) = 5
                        AND task_time GLOB '[0-2][0-9]:[0-5][0-9]'
                        AND task_time <= '23:59'
                    ),
                FOREIGN KEY (student_id) REFERENCES students(student_id)
                    ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_students_notification_preferences
            AFTER INSERT ON students
            BEGIN
                INSERT OR IGNORE INTO notification_preferences (student_id)
                VALUES (NEW.student_id);
            END
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS subjects (
                subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                subject_name TEXT COLLATE NOCASE NOT NULL,
                total_scheduled_classes INTEGER NOT NULL,
                minimum_percentage REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (student_id, subject_name),
                FOREIGN KEY (student_id) REFERENCES students(student_id)
                    ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                subject_id INTEGER,
                title TEXT NOT NULL CHECK (length(trim(title)) > 0),
                description TEXT,
                deadline TEXT NOT NULL
                    CHECK (
                        length(deadline) = 10
                        AND date(deadline) IS NOT NULL
                        AND date(deadline) = deadline
                    ),
                status TEXT NOT NULL DEFAULT 'Pending'
                    CHECK (status IN ('Pending', 'Completed')),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(student_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (subject_id) REFERENCES subjects(subject_id)
                    ON DELETE SET NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_logs (
                notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL
                    CHECK (notification_type IN ('attendance', 'task')),
                task_id INTEGER,
                notification_date TEXT NOT NULL
                    CHECK (
                        length(notification_date) = 10
                        AND date(notification_date) IS NOT NULL
                        AND date(notification_date) = notification_date
                    ),
                scheduled_time TEXT NOT NULL
                    CHECK (
                        length(scheduled_time) = 5
                        AND scheduled_time GLOB '[0-2][0-9]:[0-5][0-9]'
                        AND scheduled_time <= '23:59'
                    ),
                recipient TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sent', 'failed', 'skipped')),
                error_details TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(student_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                    ON DELETE SET NULL,
                CHECK (
                    (notification_type = 'attendance' AND task_id IS NULL)
                    OR notification_type = 'task'
                )
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS timetable_entries (
                timetable_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                day_of_week TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                period_number INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(student_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (subject_id) REFERENCES subjects(subject_id)
                    ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_subjects_student_created_at
            ON subjects (student_id, created_at DESC, subject_id DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_student_status_deadline
            ON tasks (student_id, status, deadline, created_at, task_id)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_attendance_daily
            ON notification_logs (student_id, notification_date)
            WHERE notification_type = 'attendance' AND task_id IS NULL
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_task_daily
            ON notification_logs (student_id, task_id, notification_date)
            WHERE notification_type = 'task' AND task_id IS NOT NULL
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notification_logs_student_date
            ON notification_logs (student_id, notification_date DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_timetable_student_day
            ON timetable_entries (student_id, day_of_week, start_time)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_timetable_student_entry
            ON timetable_entries (student_id, timetable_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance_records (
                attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                timetable_id INTEGER NOT NULL,
                attendance_date TEXT NOT NULL
                    CHECK (
                        length(attendance_date) = 10
                        AND date(attendance_date) IS NOT NULL
                        AND date(attendance_date) = attendance_date
                    ),
                status TEXT NOT NULL CHECK (status IN ('P', 'A', 'NA')),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (timetable_id, attendance_date),
                FOREIGN KEY (student_id) REFERENCES students(student_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (student_id, timetable_id)
                    REFERENCES timetable_entries(student_id, timetable_id)
                    ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_attendance_student_date
            ON attendance_records (student_id, attendance_date DESC)
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO notification_preferences (student_id)
            SELECT student_id FROM students
            """
        )
        connection.commit()
    finally:
        connection.close()