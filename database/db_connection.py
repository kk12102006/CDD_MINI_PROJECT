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
        connection.commit()
    finally:
        connection.close()