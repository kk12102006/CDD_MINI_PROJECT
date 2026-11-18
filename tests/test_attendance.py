import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta

from app import create_app
from config import Config
from database.db_connection import get_db_connection


class AttendanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="attendance-tests-")
        self.database_path = os.path.join(self.temp_dir.name, "test.db")
        test_config = type(
            "TestConfig",
            (Config,),
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SECRET_KEY": "test-key",
                "DATABASE": self.database_path,
                "UPLOAD_FOLDER": os.path.join(self.temp_dir.name, "uploads"),
            },
        )
        self.app = create_app(test_config)
        self.client = self.app.test_client()
        self._register_and_login("Alice", "A001", "alice@example.test")
        self._create_subject("Java", 2)
        self._create_subject("DBMS", 20)
        self._create_timetable()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _register_and_login(self, name, usn, email):
        self.client.post(
            "/register",
            data={
                "name": name,
                "usn": usn,
                "email": email,
                "password": "securepass123",
                "confirm_password": "securepass123",
            },
        )
        response = self.client.post(
            "/login",
            data={"identifier": usn, "password": "securepass123"},
        )
        self.assertEqual(response.status_code, 302)

    def _create_subject(self, subject_name, total_classes):
        response = self.client.post(
            "/subjects/add",
            data={
                "subject_name": subject_name,
                "total_scheduled_classes": str(total_classes),
                "minimum_percentage": "75",
                "credits": "1",
            },
        )
        self.assertEqual(response.status_code, 302)

    def _create_timetable(self):
        with self.app.app_context():
            with get_db_connection() as connection:
                student_id = connection.execute(
                    "SELECT student_id FROM students WHERE usn = 'A001'"
                ).fetchone()["student_id"]
                java_id = connection.execute(
                    "SELECT subject_id FROM subjects "
                    "WHERE student_id = ? AND subject_name = 'Java'",
                    (student_id,),
                ).fetchone()["subject_id"]
                dbms_id = connection.execute(
                    "SELECT subject_id FROM subjects "
                    "WHERE student_id = ? AND subject_name = 'DBMS'",
                    (student_id,),
                ).fetchone()["subject_id"]
                first_period = connection.execute(
                    """
                    INSERT INTO timetable_entries (
                        student_id, subject_id, day_of_week,
                        start_time, end_time, period_number
                    ) VALUES (?, ?, 'Monday', '09:00', '10:00', 1)
                    """,
                    (student_id, java_id),
                ).lastrowid
                second_period = connection.execute(
                    """
                    INSERT INTO timetable_entries (
                        student_id, subject_id, day_of_week,
                        start_time, end_time, period_number
                    ) VALUES (?, ?, 'Monday', '10:00', '11:00', 2)
                    """,
                    (student_id, java_id),
                ).lastrowid
                tuesday_period = connection.execute(
                    """
                    INSERT INTO timetable_entries (
                        student_id, subject_id, day_of_week,
                        start_time, end_time, period_number
                    ) VALUES (?, ?, 'Tuesday', '11:00', '12:00', 1)
                    """,
                    (student_id, dbms_id),
                ).lastrowid
                self.student_id = student_id
                self.java_id = java_id
                self.first_period = first_period
                self.second_period = second_period
                self.tuesday_period = tuesday_period

    @staticmethod
    def _past_monday():
        today = date.today()
        days_since_monday = today.weekday()
        if days_since_monday == 0:
            days_since_monday = 7
        return today - timedelta(days=days_since_monday)

    def _attendance_data(self, attendance_date, first_status, second_status):
        return {
            "attendance_date": attendance_date.isoformat(),
            f"status_{self.first_period}": first_status,
            f"status_{self.second_period}": second_status,
        }

    def _record(self, timetable_id, attendance_date):
        with self.app.app_context():
            with get_db_connection() as connection:
                return connection.execute(
                    """
                    SELECT attendance_id, status
                    FROM attendance_records
                    WHERE student_id = ? AND timetable_id = ?
                      AND attendance_date = ?
                    """,
                    (
                        self.student_id,
                        timetable_id,
                        attendance_date.isoformat(),
                    ),
                ).fetchone()

    def test_weekday_filter_and_separate_periods(self):
        monday = self._past_monday()
        monday_html = self.client.get(
            f"/attendance?date={monday.isoformat()}"
        ).get_data(as_text=True)
        self.assertEqual(monday_html.count("attendance-period-card"), 2)
        self.assertEqual(monday_html.count(">Java</h2>"), 2)
        self.assertNotIn(">DBMS</h2>", monday_html)

        tuesday_html = self.client.get(
            f"/attendance?date={(monday + timedelta(days=1)).isoformat()}"
        ).get_data(as_text=True)
        self.assertIn(">DBMS</h2>", tuesday_html)
        self.assertNotIn(">Java</h2>", tuesday_html)

    def test_na_does_not_count_and_maximum_applies_per_subject(self):
        monday = self._past_monday()
        earlier_monday = monday - timedelta(days=7)
        self.client.post(
            "/attendance/save",
            data=self._attendance_data(earlier_monday, "P", "NA"),
        )

        with self.app.app_context():
            with get_db_connection() as connection:
                self.assertEqual(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM attendance_records
                        WHERE student_id = ? AND status IN ('P', 'A')
                        """,
                        (self.student_id,),
                    ).fetchone()[0],
                    1,
                )

        response = self.client.post(
            "/attendance/save",
            data=self._attendance_data(monday, "A", "P"),
            follow_redirects=True,
        )
        self.assertIn(
            "Maximum number of classes (2) reached",
            response.get_data(as_text=True),
        )
        self.assertEqual(self._record(self.first_period, monday)["status"], "A")
        self.assertIsNone(self._record(self.second_period, monday))

    def test_saving_updates_records_and_edit_respects_the_cap(self):
        monday = self._past_monday()
        earlier_monday = monday - timedelta(days=7)
        self.client.post(
            "/attendance/save",
            data=self._attendance_data(earlier_monday, "P", "NA"),
        )
        self.client.post(
            "/attendance/save",
            data=self._attendance_data(monday, "A", "P"),
        )

        self.client.post(
            "/attendance/save",
            data=self._attendance_data(earlier_monday, "A", "NA"),
        )
        with self.app.app_context():
            with get_db_connection() as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM attendance_records WHERE student_id = ?",
                        (self.student_id,),
                    ).fetchone()[0],
                    3,
                )
                first_record = connection.execute(
                    """
                    SELECT attendance_id FROM attendance_records
                    WHERE student_id = ? AND timetable_id = ?
                      AND attendance_date = ?
                    """,
                    (
                        self.student_id,
                        self.first_period,
                        earlier_monday.isoformat(),
                    ),
                ).fetchone()
                no_class_record = connection.execute(
                    """
                    SELECT attendance_id FROM attendance_records
                    WHERE student_id = ? AND timetable_id = ?
                      AND attendance_date = ?
                    """,
                    (
                        self.student_id,
                        self.second_period,
                        earlier_monday.isoformat(),
                    ),
                ).fetchone()

        response = self.client.post(
            f"/attendance/edit/{no_class_record['attendance_id']}",
            data={"status": "P"},
            follow_redirects=True,
        )
        self.assertIn(
            "Maximum number of classes (2) reached",
            response.get_data(as_text=True),
        )
        self.assertEqual(
            self._record(self.second_period, earlier_monday)["status"], "NA"
        )

        self.client.post(
            f"/attendance/edit/{first_record['attendance_id']}",
            data={"status": "A"},
        )
        self.assertEqual(
            self._record(self.first_period, earlier_monday)["status"], "A"
        )
        history = self.client.get(
            f"/attendance/history?date={earlier_monday.isoformat()}"
        ).get_data(as_text=True)
        self.assertIn("No class", history)
        self.assertIn("Java", history)

    def test_future_dates_empty_history_and_private_records(self):
        future = date.today() + timedelta(days=1)
        self.assertEqual(
            self.client.get(f"/attendance?date={future.isoformat()}").status_code,
            302,
        )
        self.assertEqual(
            self.client.post(
                "/attendance/save",
                data={"attendance_date": future.isoformat()},
            ).status_code,
            302,
        )
        no_records = self.client.get(
            f"/attendance/history?date={self._past_monday().isoformat()}"
        ).get_data(as_text=True)
        self.assertIn("No attendance records found for this date.", no_records)

        monday = self._past_monday()
        self.client.post(
            "/attendance/save",
            data=self._attendance_data(monday, "P", "NA"),
        )
        record = self._record(self.first_period, monday)
        self.client.post("/logout")
        self._register_and_login("Bob", "B001", "bob@example.test")

        history = self.client.get("/attendance/history").get_data(as_text=True)
        self.assertNotIn(">Java</strong>", history)
        self.assertEqual(
            self.client.get(
                f"/attendance/edit/{record['attendance_id']}"
            ).status_code,
            302,
        )

    def test_database_constraints_and_subject_totals_are_preserved(self):
        monday = self._past_monday()
        self.client.post(
            "/attendance/save",
            data=self._attendance_data(monday, "P", "NA"),
        )
        with self.app.app_context():
            with get_db_connection() as connection:
                record = connection.execute(
                    """
                    SELECT attendance_id FROM attendance_records
                    WHERE student_id = ? AND timetable_id = ?
                      AND attendance_date = ?
                    """,
                    (
                        self.student_id,
                        self.first_period,
                        monday.isoformat(),
                    ),
                ).fetchone()
                self.assertEqual(
                    connection.execute(
                        "SELECT total_scheduled_classes FROM subjects WHERE subject_id = ?",
                        (self.java_id,),
                    ).fetchone()[0],
                    2,
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO attendance_records (
                            student_id, timetable_id, attendance_date, status
                        ) VALUES (?, ?, ?, 'A')
                        """,
                        (self.student_id, self.first_period, monday.isoformat()),
                    )

                bob_id = connection.execute(
                    """
                    INSERT INTO students (name, usn, email, password_hash)
                    VALUES ('Bob', 'B002', 'bob2@example.test', 'hash')
                    """
                ).lastrowid
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO attendance_records (
                            student_id, timetable_id, attendance_date, status
                        ) VALUES (?, ?, ?, 'P')
                        """,
                        (bob_id, self.first_period, monday.isoformat()),
                    )
                self.assertIsNotNone(record)


if __name__ == "__main__":
    unittest.main()
