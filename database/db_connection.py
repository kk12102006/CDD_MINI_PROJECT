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
            CREATE INDEX IF NOT EXISTS idx_timetable_student_day
            ON timetable_entries (student_id, day_of_week, start_time)
            """
        )
        connection.commit()
    finally:
        connection.close()