import os
import tempfile
import unittest

from app import create_app
from config import Config
from database.db_connection import get_db_connection
from services.attendance_calculator import (
    calculate_subject_attendance,
    get_subject_attendance_overview,
)


SUBJECT = {
    "subject_id": 1,
    "subject_name": "Java",
    "total_scheduled_classes": 50,
    "minimum_percentage": 85,
}


class AttendanceCalculationTests(unittest.TestCase):
    def test_satisfactory_subject_statistics_and_na_exclusion(self):
        result = calculate_subject_attendance(
            SUBJECT, {"present": 35, "absent": 5, "no_class": 2}
        )
        self.assertEqual(result["completed_classes"], 40)
        self.assertEqual(result["attendance_percentage_display"], "87.50%")
        self.assertEqual(result["maximum_allowed_absences"], 7)
        self.assertEqual(result["remaining_allowed_absences"], 2)
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["attendance_status"], "satisfactory")

    def test_deadline_warning_is_distinct_from_shortage(self):
        at_limit = calculate_subject_attendance(
            SUBJECT, {"present": 33, "absent": 7, "no_class": 0}
        )
        self.assertEqual(at_limit["attendance_percentage_display"], "82.50%")
        self.assertEqual(at_limit["remaining_allowed_absences"], 0)
        self.assertEqual(
            [warning["code"] for warning in at_limit["warnings"]],
            ["deadline"],
        )
        self.assertEqual(at_limit["attendance_status"], "below_required")

        over_limit = calculate_subject_attendance(
            SUBJECT, {"present": 32, "absent": 8, "no_class": 0}
        )
        self.assertEqual(over_limit["attendance_percentage_display"], "80.00%")
        self.assertEqual(over_limit["remaining_allowed_absences"], 0)
        self.assertEqual(
            [warning["code"] for warning in over_limit["warnings"]],
            ["deadline", "shortage"],
        )

    def test_na_only_has_no_percentage_or_absence_warning(self):
        result = calculate_subject_attendance(
            SUBJECT, {"present": 0, "absent": 0, "no_class": 5}
        )
        self.assertEqual(result["completed_classes"], 0)
        self.assertEqual(result["attendance_percentage_display"], "N/A")
        self.assertEqual(result["maximum_allowed_absences"], 7)
        self.assertEqual(result["remaining_allowed_absences"], 7)
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["attendance_status"], "not_available")

    def test_maximum_absences_uses_floor_and_percentage_is_capped(self):
        subject = dict(SUBJECT, total_scheduled_classes=33, minimum_percentage=90)
        result = calculate_subject_attendance(
            subject, {"present": 5, "absent": 0, "no_class": 0}
        )
        self.assertEqual(result["maximum_allowed_absences"], 3)
        self.assertEqual(result["attendance_percentage"], 100)
        self.assertLessEqual(result["progress_percentage"], 100)

    def test_database_overview_is_separate_by_subject_and_student(self):
        with tempfile.TemporaryDirectory(prefix="attendance-overview-") as temp_dir:
            test_config = type(
                "TestConfig",
                (Config,),
                {
                    "TESTING": True,
                    "WTF_CSRF_ENABLED": False,
                    "SECRET_KEY": "overview-test-key",
                    "DATABASE": os.path.join(temp_dir, "test.db"),
                    "UPLOAD_FOLDER": os.path.join(temp_dir, "uploads"),
                },
            )
            app = create_app(test_config)
            with app.app_context():
                with get_db_connection() as connection:
                    student_id = connection.execute(
                        """
                        INSERT INTO students (name, usn, email, password_hash)
                        VALUES ('Alice', 'OV001', 'overview@example.test', 'hash')
                        """
                    ).lastrowid
                    java_id = connection.execute(
                        """
                        INSERT INTO subjects (
                            student_id, subject_name, total_scheduled_classes,
                            minimum_percentage
                        ) VALUES (?, 'Java', 50, 85)
                        """,
                        (student_id,),
                    ).lastrowid
                    dbms_id = connection.execute(
                        """
                        INSERT INTO subjects (
                            student_id, subject_name, total_scheduled_classes,
                            minimum_percentage
                        ) VALUES (?, 'DBMS', 45, 75)
                        """,
                        (student_id,),
                    ).lastrowid
                    java_periods = []
                    for start, end in (
                        ("09:00", "10:00"),
                        ("10:00", "11:00"),
                        ("11:00", "12:00"),
                    ):
                        java_periods.append(
                            connection.execute(
                                """
                                INSERT INTO timetable_entries (
                                    student_id, subject_id, day_of_week,
                                    start_time, end_time
                                ) VALUES (?, ?, 'Monday', ?, ?)
                                """,
                                (student_id, java_id, start, end),
                            ).lastrowid
                        )
                    dbms_period = connection.execute(
                        """
                        INSERT INTO timetable_entries (
                            student_id, subject_id, day_of_week,
                            start_time, end_time
                        ) VALUES (?, ?, 'Tuesday', '09:00', '10:00')
                        """,
                        (student_id, dbms_id),
                    ).lastrowid
                    java_attendance_ids = []
                    for timetable_id, status in zip(
                        java_periods, ("P", "A", "NA")
                    ):
                        java_attendance_ids.append(
                            connection.execute(
                                """
                                INSERT INTO attendance_records (
                                    student_id, timetable_id,
                                    attendance_date, status
                                ) VALUES (?, ?, '2026-11-02', ?)
                                """,
                                (student_id, timetable_id, status),
                            ).lastrowid
                        )
                    connection.execute(
                        """
                        INSERT INTO attendance_records (
                            student_id, timetable_id, attendance_date, status
                        ) VALUES (?, ?, '2026-11-03', 'P')
                        """,
                        (student_id, dbms_period),
                    )

            client = app.test_client()
            self.assertEqual(client.get("/attendance/overview").status_code, 302)
            with client.session_transaction() as browser_session:
                browser_session["student_id"] = student_id
            response = client.get("/attendance/overview")
            page = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn("Java", page)
            self.assertIn("DBMS", page)

            with app.app_context():
                summaries = get_subject_attendance_overview(student_id)
                by_name = {item["subject_name"]: item for item in summaries}
                self.assertEqual(
                    (
                        by_name["Java"]["present_classes"],
                        by_name["Java"]["absent_classes"],
                        by_name["Java"]["no_class_entries"],
                    ),
                    (1, 1, 1),
                )
                self.assertEqual(
                    (
                        by_name["DBMS"]["present_classes"],
                        by_name["DBMS"]["absent_classes"],
                        by_name["DBMS"]["no_class_entries"],
                    ),
                    (1, 0, 0),
                )

            client.post(
                f"/attendance/edit/{java_attendance_ids[0]}",
                data={"status": "A"},
            )
            with app.app_context():
                java_after_present_correction = {
                    item["subject_name"]: item
                    for item in get_subject_attendance_overview(student_id)
                }["Java"]
                self.assertEqual(
                    (
                        java_after_present_correction["present_classes"],
                        java_after_present_correction["absent_classes"],
                        java_after_present_correction["completed_classes"],
                        java_after_present_correction["attendance_percentage"],
                    ),
                    (0, 2, 2, 0),
                )

            client.post(
                f"/attendance/edit/{java_attendance_ids[1]}",
                data={"status": "NA"},
            )
            with app.app_context():
                java_after_na_correction = {
                    item["subject_name"]: item
                    for item in get_subject_attendance_overview(student_id)
                }["Java"]
                self.assertEqual(
                    (
                        java_after_na_correction["present_classes"],
                        java_after_na_correction["absent_classes"],
                        java_after_na_correction["no_class_entries"],
                        java_after_na_correction["completed_classes"],
                        java_after_na_correction["attendance_percentage"],
                    ),
                    (0, 1, 2, 1, 0),
                )

                with get_db_connection() as connection:
                    other_student_id = connection.execute(
                        """
                        INSERT INTO students (name, usn, email, password_hash)
                        VALUES ('Bob', 'OV002', 'other@example.test', 'hash')
                        """
                    ).lastrowid

            with client.session_transaction() as browser_session:
                browser_session["student_id"] = other_student_id
            other_page = client.get("/attendance/overview").get_data(as_text=True)
            self.assertIn("No subjects to summarize yet.", other_page)
            self.assertNotIn("Java", other_page)


if __name__ == "__main__":
    unittest.main()
