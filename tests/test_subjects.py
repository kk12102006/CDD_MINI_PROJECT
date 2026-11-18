from io import BytesIO
import os
import sqlite3
import tempfile
import unittest

import fitz

from app import create_app
from config import Config
from database.db_connection import get_db_connection, init_db


class SubjectTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="attendance-subjects-")
        self.database_path = os.path.join(self.temp_dir.name, "test.db")
        test_config = type(
            "TestConfig",
            (Config,),
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SECRET_KEY": "subjects-test-key",
                "DATABASE": self.database_path,
                "UPLOAD_FOLDER": os.path.join(self.temp_dir.name, "uploads"),
            },
        )
        self.app = create_app(test_config)
        self.client = self.app.test_client()
        with self.app.app_context():
            with get_db_connection() as connection:
                self.alice_id = connection.execute(
                    """
                    INSERT INTO students (name, usn, email, password_hash)
                    VALUES ('Alice', 'SUBJECT001', 'alice-subjects@example.test', 'hash')
                    """
                ).lastrowid
                self.bob_id = connection.execute(
                    """
                    INSERT INTO students (name, usn, email, password_hash)
                    VALUES ('Bob', 'SUBJECT002', 'bob-subjects@example.test', 'hash')
                    """
                ).lastrowid
        self._login_as(self.alice_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _login_as(self, student_id):
        with self.client.session_transaction() as browser_session:
            browser_session["student_id"] = student_id

    def _add_subject_data(self, name="Java", credits="4"):
        return {
            "subject_name": name,
            "total_scheduled_classes": "50",
            "minimum_percentage": "85",
            "credits": credits,
        }

    def _create_subject(self, student_id, name="Java"):
        with self.app.app_context():
            with get_db_connection() as connection:
                return connection.execute(
                    """
                    INSERT INTO subjects (
                        student_id, subject_name, total_scheduled_classes,
                        minimum_percentage
                    ) VALUES (?, ?, 50, 85)
                    """,
                    (student_id, name),
                ).lastrowid

    def _subject(self, subject_id):
        with self.app.app_context():
            with get_db_connection() as connection:
                return connection.execute(
                    "SELECT * FROM subjects WHERE subject_id = ?",
                    (subject_id,),
                ).fetchone()

    def test_add_subject_stores_and_displays_integer_and_decimal_credits(self):
        for name, credits in (
            ("Java", "4"),
            ("DBMS", "3.5"),
            ("Mathematics", "3.1415927"),
        ):
            response = self.client.post(
                "/subjects/add",
                data=self._add_subject_data(name, credits),
            )
            self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            with get_db_connection() as connection:
                saved_credits = connection.execute(
                    """
                    SELECT subject_name, credits FROM subjects
                    WHERE student_id = ? ORDER BY subject_name
                    """,
                    (self.alice_id,),
                ).fetchall()
                mathematics_id = connection.execute(
                    """
                    SELECT subject_id FROM subjects
                    WHERE student_id = ? AND subject_name = 'Mathematics'
                    """,
                    (self.alice_id,),
                ).fetchone()["subject_id"]
        self.assertEqual(
            [(row["subject_name"], row["credits"]) for row in saved_credits],
            [("DBMS", 3.5), ("Java", 4.0), ("Mathematics", 3.1415927)],
        )

        subjects_page = self.client.get("/subjects").get_data(as_text=True)
        dashboard_page = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("3.5", subjects_page)
        self.assertIn("4", subjects_page)
        self.assertIn("3.1415927", subjects_page)
        self.assertIn("3.1415927 credits", dashboard_page)
        report_page = self.client.get(
            f"/reports/subject/{mathematics_id}"
        ).get_data(as_text=True)
        self.assertIn("3.1415927 credits", report_page)

    def test_add_rejects_non_positive_empty_and_non_numeric_credits(self):
        for credits, message in (
            ("0", "Credits must be a positive number."),
            ("-1", "Credits must be a positive number."),
            ("", "Credits are required."),
            ("invalid", "Credits must be a positive number."),
            ("nan", "Credits must be a positive number."),
            ("inf", "Credits must be a positive number."),
        ):
            with self.subTest(credits=credits):
                response = self.client.post(
                    "/subjects/add",
                    data=self._add_subject_data(
                        name="Invalid " + (credits or "empty"),
                        credits=credits,
                    ),
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(message, response.get_data(as_text=True))

        with self.app.app_context():
            with get_db_connection() as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM subjects WHERE student_id = ?",
                    (self.alice_id,),
                ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_edit_updates_credits_without_changing_attendance_records(self):
        subject_id = self._create_subject(self.alice_id)
        with self.app.app_context():
            with get_db_connection() as connection:
                timetable_id = connection.execute(
                    """
                    INSERT INTO timetable_entries (
                        student_id, subject_id, day_of_week,
                        start_time, end_time, period_number
                    ) VALUES (?, ?, 'Monday', '09:00', '10:00', 1)
                    """,
                    (self.alice_id, subject_id),
                ).lastrowid
                connection.execute(
                    """
                    INSERT INTO attendance_records (
                        student_id, timetable_id, attendance_date, status
                    ) VALUES (?, ?, '2026-11-17', 'P')
                    """,
                    (self.alice_id, timetable_id),
                )

        edit_page = self.client.get(f"/subjects/edit/{subject_id}")
        self.assertEqual(edit_page.status_code, 200)
        edit_page_html = edit_page.get_data(as_text=True)
        self.assertIn('name="credits"', edit_page_html)
        self.assertIn('value="0.0"', edit_page_html)

        response = self.client.post(
            f"/subjects/edit/{subject_id}",
            data=self._add_subject_data(credits="2.75"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._subject(subject_id)["credits"], 2.75)
        with self.app.app_context():
            with get_db_connection() as connection:
                attendance = connection.execute(
                    """
                    SELECT status FROM attendance_records
                    WHERE timetable_id = ?
                    """,
                    (timetable_id,),
                ).fetchone()
        self.assertEqual(attendance["status"], "P")

    def test_duplicate_names_and_other_students_subjects_remain_protected(self):
        own_subject_id = self._create_subject(self.alice_id, "Java")
        other_subject_id = self._create_subject(self.bob_id, "Private subject")

        duplicate_response = self.client.post(
            "/subjects/add",
            data=self._add_subject_data(name="java", credits="3"),
        )
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertIn(
            "already added a subject",
            duplicate_response.get_data(as_text=True),
        )

        unauthorized_response = self.client.post(
            f"/subjects/edit/{other_subject_id}",
            data=self._add_subject_data(name="Private subject", credits="9"),
        )
        self.assertEqual(unauthorized_response.status_code, 302)
        self.assertEqual(self._subject(other_subject_id)["credits"], 0)
        self.assertEqual(self._subject(own_subject_id)["credits"], 0)

    def test_pdf_timetable_matching_still_uses_subject_names(self):
        response = self.client.post(
            "/subjects/add",
            data=self._add_subject_data(name="Java", credits="3.5"),
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            with get_db_connection() as connection:
                subject_id = connection.execute(
                    """
                    SELECT subject_id FROM subjects
                    WHERE student_id = ? AND subject_name = 'Java'
                    """,
                    (self.alice_id,),
                ).fetchone()["subject_id"]

        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Monday 9:00 AM - 10:00 AM Java")
        pdf_bytes = document.tobytes()
        document.close()
        response = self.client.post(
            "/timetable/upload",
            data={"pdf_file": (BytesIO(pdf_bytes), "schedule.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as browser_session:
            preview_entry = browser_session["timetable_preview"][0]
        self.assertEqual(preview_entry["subject_id"], subject_id)
        self.assertEqual(preview_entry["subject_name"], "Java")
        self.assertEqual(preview_entry["day_of_week"], "Monday")

    def test_legacy_subject_migration_is_in_place_and_idempotent(self):
        legacy_database = os.path.join(self.temp_dir.name, "legacy.db")
        connection = sqlite3.connect(legacy_database)
        try:
            connection.executescript(
                """
                CREATE TABLE students (
                    student_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    usn TEXT COLLATE NOCASE UNIQUE NOT NULL,
                    email TEXT COLLATE NOCASE UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE subjects (
                    subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    subject_name TEXT COLLATE NOCASE NOT NULL,
                    total_scheduled_classes INTEGER NOT NULL,
                    minimum_percentage REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (student_id, subject_name),
                    FOREIGN KEY (student_id) REFERENCES students(student_id)
                        ON DELETE CASCADE
                );
                INSERT INTO students (name, usn, email, password_hash)
                VALUES ('Legacy student', 'LEGACY001', 'legacy@example.test', 'hash');
                INSERT INTO subjects (
                    student_id, subject_name, total_scheduled_classes,
                    minimum_percentage
                ) VALUES (1, 'Legacy subject', 42, 75);
                """
            )
            connection.commit()
        finally:
            connection.close()

        init_db(legacy_database)
        init_db(legacy_database)

        connection = sqlite3.connect(legacy_database)
        try:
            subject = connection.execute(
                """
                SELECT subject_id, student_id, subject_name,
                       total_scheduled_classes, minimum_percentage, credits
                FROM subjects
                """
            ).fetchone()
            credits_column = next(
                column
                for column in connection.execute("PRAGMA table_info(subjects)")
                if column[1] == "credits"
            )
            student_count = connection.execute(
                "SELECT COUNT(*) FROM students"
            ).fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(subject, (1, 1, "Legacy subject", 42, 75.0, 0.0))
        self.assertEqual(credits_column[3], 1)
        self.assertEqual(credits_column[4], "0")
        self.assertEqual(student_count, 1)


if __name__ == "__main__":
    unittest.main()
