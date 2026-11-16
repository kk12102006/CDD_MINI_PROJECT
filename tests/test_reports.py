import os
import tempfile
import unittest
from datetime import date, timedelta
from io import BytesIO

import pymupdf
from openpyxl import load_workbook

from app import create_app
from config import Config
from database.db_connection import get_db_connection
from services.report_service import (
    create_present_absent_chart,
    create_monthly_attendance_chart,
    create_subject_attendance_chart,
    get_monthly_attendance,
    get_overall_summary,
    get_report_overview,
    parse_report_filters,
)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="attendance-reports-")
        self.database_path = os.path.join(self.temp_dir.name, "test.db")
        test_config = type(
            "TestConfig",
            (Config,),
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SECRET_KEY": "reports-test-key",
                "DATABASE": self.database_path,
                "UPLOAD_FOLDER": os.path.join(self.temp_dir.name, "uploads"),
            },
        )
        self.app = create_app(test_config)
        self.client = self.app.test_client()
        self._create_data()
        with self.client.session_transaction() as browser_session:
            browser_session["student_id"] = self.alice_id

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_data(self):
        today = date.today()
        with self.app.app_context():
            with get_db_connection() as connection:
                self.alice_id = connection.execute(
                    """
                    INSERT INTO students (name, usn, email, password_hash)
                    VALUES ('Alice Example', 'AL001', 'alice@example.test', 'hash')
                    """
                ).lastrowid
                self.bob_id = connection.execute(
                    """
                    INSERT INTO students (name, usn, email, password_hash)
                    VALUES ('Bob Private', 'BO001', 'bob@example.test', 'hash')
                    """
                ).lastrowid
                self.empty_student_id = connection.execute(
                    """
                    INSERT INTO students (name, usn, email, password_hash)
                    VALUES ('Casey Empty', 'CE001', 'casey@example.test', 'hash')
                    """
                ).lastrowid

                self.math_id = connection.execute(
                    """
                    INSERT INTO subjects (
                        student_id, subject_name, total_scheduled_classes,
                        minimum_percentage
                    ) VALUES (?, 'Mathematics', 10, 75)
                    """,
                    (self.alice_id,),
                ).lastrowid
                self.history_id = connection.execute(
                    """
                    INSERT INTO subjects (
                        student_id, subject_name, total_scheduled_classes,
                        minimum_percentage
                    ) VALUES (?, 'History', 10, 80)
                    """,
                    (self.alice_id,),
                ).lastrowid
                self.chemistry_id = connection.execute(
                    """
                    INSERT INTO subjects (
                        student_id, subject_name, total_scheduled_classes,
                        minimum_percentage
                    ) VALUES (?, 'Chemistry', 4, 75)
                    """,
                    (self.alice_id,),
                ).lastrowid
                self.private_subject_id = connection.execute(
                    """
                    INSERT INTO subjects (
                        student_id, subject_name, total_scheduled_classes,
                        minimum_percentage
                    ) VALUES (?, 'Private Subject', 5, 75)
                    """,
                    (self.bob_id,),
                ).lastrowid

                periods = {}
                for student_id, subject_id, start_time in (
                    (self.alice_id, self.math_id, "09:00"),
                    (self.alice_id, self.history_id, "10:00"),
                    (self.alice_id, self.chemistry_id, "11:00"),
                    (self.bob_id, self.private_subject_id, "12:00"),
                ):
                    periods[subject_id] = connection.execute(
                        """
                        INSERT INTO timetable_entries (
                            student_id, subject_id, day_of_week,
                            start_time, end_time, period_number
                        ) VALUES (?, ?, 'Monday', ?, '13:00', 1)
                        """,
                        (student_id, subject_id, start_time),
                    ).lastrowid
                self.math_period = periods[self.math_id]
                self.history_period = periods[self.history_id]
                self.chemistry_period = periods[self.chemistry_id]
                bob_period = periods[self.private_subject_id]

                records = (
                    (self.math_period, today - timedelta(days=2), "NA"),
                    (self.math_period, today - timedelta(days=1), "P"),
                    (self.math_period, today, "A"),
                    (self.history_period, today, "P"),
                    (self.chemistry_period, today - timedelta(days=1), "A"),
                    (self.chemistry_period, today, "A"),
                    (bob_period, today, "P"),
                )
                for timetable_id, attendance_date, status in records:
                    student_id = (
                        self.bob_id
                        if timetable_id == bob_period
                        else self.alice_id
                    )
                    connection.execute(
                        """
                        INSERT INTO attendance_records (
                            student_id, timetable_id, attendance_date, status
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (student_id, timetable_id, attendance_date.isoformat(), status),
                    )
        self.today = today

    def test_summary_monthly_totals_and_alerts_are_calculated_from_saved_records(self):
        with self.app.app_context():
            overview = get_report_overview(self.alice_id)
            summary = overview["summary"]
            self.assertEqual(overview["student"]["name"], "Alice Example")
            self.assertEqual(summary["present_classes"], 2)
            self.assertEqual(summary["absent_classes"], 3)
            self.assertEqual(summary["no_class_entries"], 1)
            self.assertEqual(summary["attendance_percentage_display"], "40.00%")
            self.assertEqual(summary["satisfactory_subjects"], 1)
            self.assertEqual(summary["below_required_subjects"], 2)
            self.assertEqual(summary["absence_deadline_subjects"], 1)
            self.assertEqual(summary["shortage_subjects"], 1)

            monthly = get_monthly_attendance(
                self.alice_id, self.today.year, self.today.month
            )
            self.assertEqual(
                (
                    monthly["present_classes"],
                    monthly["absent_classes"],
                    monthly["no_class_entries"],
                    monthly["completed_classes"],
                    monthly["attendance_percentage_display"],
                ),
                (2, 3, 1, 5, "40.00%"),
            )
            single_subject = get_monthly_attendance(
                self.alice_id,
                self.today.year,
                self.today.month,
                self.math_id,
            )
            self.assertEqual(single_subject["completed_classes"], 2)
            self.assertEqual(single_subject["no_class_entries"], 1)

    def test_reports_dashboard_monthly_and_date_filters_are_student_scoped(self):
        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("40.00%", dashboard.get_data(as_text=True))

        reports = self.client.get("/reports")
        page = reports.get_data(as_text=True)
        self.assertEqual(reports.status_code, 200)
        self.assertIn("Mathematics", page)
        self.assertIn("ATTENDANCE SHORTAGE", page)
        self.assertNotIn("Private Subject", page)

        datewise = self.client.get(
            "/reports/date-wise",
            query_string={
                "start_date": (self.today - timedelta(days=1)).isoformat(),
                "end_date": self.today.isoformat(),
                "status": "P",
            },
        )
        page = datewise.get_data(as_text=True)
        self.assertEqual(datewise.status_code, 200)
        self.assertIn("2 records", page)
        self.assertIn("Mathematics", page)
        self.assertNotIn("<strong>Chemistry</strong>", page)
        self.assertNotIn("Private Subject", page)

        monthly = self.client.get(
            "/reports/monthly",
            query_string={
                "month": self.today.month,
                "year": self.today.year,
                "subject_id": self.math_id,
            },
        )
        self.assertEqual(monthly.status_code, 200)
        self.assertIn("50.00%", monthly.get_data(as_text=True))

        subject_page = self.client.get(f"/reports/subject/{self.math_id}")
        self.assertEqual(subject_page.status_code, 200)
        self.assertIn("Mathematics", subject_page.get_data(as_text=True))

    def test_invalid_and_other_student_filters_are_rejected(self):
        future = (self.today + timedelta(days=1)).isoformat()
        invalid_date = self.client.get(
            "/reports/date-wise",
            query_string={"start_date": future},
        )
        self.assertEqual(invalid_date.status_code, 400)

        invalid_range = self.client.get(
            "/reports/date-wise",
            query_string={
                "start_date": self.today.isoformat(),
                "end_date": (self.today - timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(invalid_range.status_code, 400)

        invalid_month = self.client.get(
            "/reports/monthly",
            query_string={"month": 13, "year": self.today.year},
        )
        self.assertEqual(invalid_month.status_code, 400)

        for path in (
            f"/reports/subject/{self.private_subject_id}",
            f"/reports/subject/{self.private_subject_id}/download/pdf",
            f"/reports/subject/{self.private_subject_id}/download/excel",
        ):
            self.assertEqual(self.client.get(path).status_code, 404)

        with self.app.app_context():
            filters, error = parse_report_filters(
                {"subject_id": str(self.private_subject_id)},
                self.alice_id,
            )
            self.assertIsNone(filters)
            self.assertIn("belonging to your account", error)

    def test_pdf_and_excel_downloads_contain_only_owned_records(self):
        pdf_response = self.client.get("/reports/download/pdf")
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, "application/pdf")
        self.assertTrue(pdf_response.data.startswith(b"%PDF"))
        pdf_text = "\n".join(
            page.get_text()
            for page in pymupdf.open(stream=pdf_response.data, filetype="pdf")
        )
        self.assertIn("Alice Example", pdf_text)
        self.assertIn("Mathematics", pdf_text)
        self.assertNotIn("Bob Private", pdf_text)
        self.assertNotIn("Private Subject", pdf_text)

        subject_pdf = self.client.get(
            f"/reports/subject/{self.math_id}/download/pdf"
        )
        self.assertEqual(subject_pdf.status_code, 200)
        self.assertTrue(subject_pdf.data.startswith(b"%PDF"))

        excel_response = self.client.get("/reports/download/excel")
        self.assertEqual(excel_response.status_code, 200)
        workbook = load_workbook(BytesIO(excel_response.data), data_only=True)
        self.assertEqual(
            workbook.sheetnames,
            ["Overall Summary", "Subject Summary", "Attendance Records"],
        )
        self.assertEqual(workbook["Overall Summary"]["B11"].value, 0.4)
        self.assertEqual(workbook["Subject Summary"].max_row, 4)
        self.assertEqual(workbook["Attendance Records"].max_row, 7)
        record_subjects = {
            workbook["Attendance Records"].cell(row, 3).value
            for row in range(2, workbook["Attendance Records"].max_row + 1)
        }
        self.assertNotIn("Private Subject", record_subjects)

        subject_excel = self.client.get(
            f"/reports/subject/{self.math_id}/download/excel"
        )
        self.assertEqual(subject_excel.status_code, 200)
        subject_workbook = load_workbook(BytesIO(subject_excel.data), data_only=True)
        self.assertEqual(subject_workbook["Subject Summary"].max_row, 2)
        self.assertEqual(subject_workbook["Attendance Records"].max_row, 4)

    def test_empty_chart_and_data_cases_are_supported(self):
        self.assertIsNone(create_subject_attendance_chart([]))
        self.assertIsNone(create_present_absent_chart(0, 0))
        self.assertIsNone(
            create_monthly_attendance_chart(
                [
                    {
                        "month_name": "Jan",
                        "present": 0,
                        "absent": 0,
                        "completed": 0,
                        "percentage": None,
                    }
                ],
                date.today().year,
            )
        )
        chart = create_present_absent_chart(2, 1)
        self.assertTrue(chart.startswith("data:image/png;base64,"))

        with self.app.app_context():
            empty_summary = get_overall_summary([])
        self.assertEqual(empty_summary["attendance_percentage_display"], "N/A")
        self.assertEqual(empty_summary["completed_classes"], 0)

    def test_empty_student_can_view_and_download_reports(self):
        with self.client.session_transaction() as browser_session:
            browser_session["student_id"] = self.empty_student_id

        page = self.client.get("/reports")
        self.assertEqual(page.status_code, 200)
        self.assertIn("No subjects are available to report yet.", page.get_data(as_text=True))

        pdf = self.client.get("/reports/download/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))

        excel = self.client.get("/reports/download/excel")
        self.assertEqual(excel.status_code, 200)
        workbook = load_workbook(BytesIO(excel.data), data_only=True)
        self.assertEqual(workbook["Subject Summary"].max_row, 1)
        self.assertEqual(workbook["Attendance Records"].max_row, 1)


if __name__ == "__main__":
    unittest.main()
