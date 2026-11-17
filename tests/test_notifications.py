import os
import smtplib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app import create_app
from config import Config
from database.db_connection import get_db_connection
from services.email_service import send_email
from services.notification_scheduler import start_scheduler, stop_scheduler
from services.notification_service import process_due_notifications


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="attendance-notifications-")
        self.database_path = os.path.join(self.temp_dir.name, "test.db")
        test_config = type(
            "TestConfig",
            (Config,),
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SECRET_KEY": "notifications-test-key",
                "DATABASE": self.database_path,
                "UPLOAD_FOLDER": os.path.join(self.temp_dir.name, "uploads"),
            },
        )
        self.app = create_app(test_config)
        self.client = self.app.test_client()
        self.now = datetime(2026, 11, 17, 7, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        with self.app.app_context():
            with get_db_connection() as connection:
                self.alice_id = connection.execute(
                    """
                    INSERT INTO students (name, usn, email, password_hash)
                    VALUES ('Alice', 'MAIL001', 'alice-mail@example.test', 'hash')
                    """
                ).lastrowid
                self.bob_id = connection.execute(
                    """
                    INSERT INTO students (name, usn, email, password_hash)
                    VALUES ('Bob', 'MAIL002', 'bob-mail@example.test', 'hash')
                    """
                ).lastrowid
        self._login_as(self.alice_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _login_as(self, student_id):
        with self.client.session_transaction() as browser_session:
            browser_session["student_id"] = student_id

    def _set_preferences(
        self,
        student_id,
        attendance_enabled=0,
        attendance_time="07:00",
        task_enabled=0,
        task_time="08:00",
    ):
        with self.app.app_context():
            with get_db_connection() as connection:
                connection.execute(
                    """
                    UPDATE notification_preferences
                    SET attendance_enabled = ?, attendance_time = ?,
                        task_enabled = ?, task_time = ?
                    WHERE student_id = ?
                    """,
                    (
                        attendance_enabled,
                        attendance_time,
                        task_enabled,
                        task_time,
                        student_id,
                    ),
                )

    def _add_subject(self, student_id, name, absences, scheduled=True):
        with self.app.app_context():
            with get_db_connection() as connection:
                subject_id = connection.execute(
                    """
                    INSERT INTO subjects (
                        student_id, subject_name, total_scheduled_classes,
                        minimum_percentage
                    ) VALUES (?, ?, 20, 75)
                    """,
                    (student_id, name),
                ).lastrowid
                day = (
                    self.now.strftime("%A")
                    if scheduled
                    else (self.now.date() + timedelta(days=1)).strftime("%A")
                )
                for index in range(max(1, absences)):
                    timetable_id = connection.execute(
                        """
                        INSERT INTO timetable_entries (
                            student_id, subject_id, day_of_week,
                            start_time, end_time, period_number
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            student_id,
                            subject_id,
                            day,
                            f"{8 + index:02d}:00",
                            f"{9 + index:02d}:00",
                            index + 1,
                        ),
                    ).lastrowid
                    if index < absences:
                        connection.execute(
                            """
                            INSERT INTO attendance_records (
                                student_id, timetable_id, attendance_date, status
                            ) VALUES (?, ?, ?, 'A')
                            """,
                            (
                                student_id,
                                timetable_id,
                                (
                                    self.now.date() - timedelta(days=index + 1)
                                ).isoformat(),
                            ),
                        )
        return subject_id

    def _add_task(self, student_id, title, days_remaining, status="Pending"):
        deadline = self.now.date() + timedelta(days=days_remaining)
        with self.app.app_context():
            with get_db_connection() as connection:
                return connection.execute(
                    """
                    INSERT INTO tasks (
                        student_id, title, deadline, status, completed_at
                    )
                    VALUES (?, ?, ?, ?, CASE WHEN ? = 'Completed'
                        THEN CURRENT_TIMESTAMP ELSE NULL END)
                    """,
                    (
                        student_id,
                        title,
                        deadline.isoformat(),
                        status,
                        status,
                    ),
                ).lastrowid

    def _logs(self, student_id):
        with self.app.app_context():
            with get_db_connection() as connection:
                return connection.execute(
                    """
                    SELECT notification_type, task_id, notification_date,
                           scheduled_time, recipient, status, error_details
                    FROM notification_logs
                    WHERE student_id = ?
                    ORDER BY notification_id
                    """,
                    (student_id,),
                ).fetchall()

    def _process(self, current_time=None):
        with self.app.app_context():
            process_due_notifications(current_time)

    def test_attendance_email_only_contains_todays_subjects_with_at_most_two_absences(self):
        self._add_subject(self.alice_id, "Java", 0)
        self._add_subject(self.alice_id, "Python", 3)
        self._add_subject(self.alice_id, "DBMS", 4)
        self._add_subject(self.alice_id, "Computer Networks", 5)
        self._add_subject(self.alice_id, "Off day subject", 4, scheduled=False)
        self._add_subject(self.bob_id, "Bob subject", 5)
        self._set_preferences(self.alice_id, attendance_enabled=1)
        self._set_preferences(
            self.bob_id,
            attendance_enabled=1,
            attendance_time="08:00",
        )

        with patch(
            "services.notification_service.send_email",
            return_value=(True, None),
        ) as send:
            self._process(
                datetime(2026, 11, 17, 1, 30, tzinfo=timezone.utc)
            )
            self.assertEqual(send.call_count, 1)
            recipient, subject, body = send.call_args.args[1:]
            self.assertEqual(recipient, "alice-mail@example.test")
            self.assertEqual(
                subject,
                "Attendance Warning – Student Attendance Manager",
            )
            self.assertIn("Python – 2 absences remaining.", body)
            self.assertIn("DBMS – 1 absence remaining.", body)
            self.assertIn("Computer Networks – 0 absences remaining.", body)
            self.assertNotIn("Java", body)
            self.assertNotIn("Off day subject", body)
            self.assertNotIn("%", body)

            self._process(self.now)
            self.assertEqual(send.call_count, 1)
            self._process(self.now.replace(hour=8))
            self.assertEqual(send.call_count, 2)
            self.assertEqual(
                send.call_args.args[1],
                "bob-mail@example.test",
            )

        alice_logs = self._logs(self.alice_id)
        self.assertEqual(len(alice_logs), 1)
        self.assertEqual(alice_logs[0]["status"], "sent")
        self.assertEqual(alice_logs[0]["scheduled_time"], "07:00")
        self.assertEqual(alice_logs[0]["recipient"], "alice-mail@example.test")

    def test_no_attendance_warnings_are_logged_without_sending_email(self):
        self._add_subject(self.alice_id, "Java", 0)
        self._set_preferences(self.alice_id, attendance_enabled=1)

        with patch("services.notification_service.send_email") as send:
            self._process(self.now)

        send.assert_not_called()
        logs = self._logs(self.alice_id)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["notification_type"], "attendance")
        self.assertEqual(logs[0]["status"], "skipped")

    def test_task_emails_classify_dates_skip_completed_and_prevent_duplicates(self):
        self._add_task(self.alice_id, "Ten days", 10)
        upcoming_id = self._add_task(self.alice_id, "Seven days", 7)
        self._add_task(self.alice_id, "Three days", 3)
        self._add_task(self.alice_id, "Due today", 0)
        self._add_task(self.alice_id, "Overdue", -1)
        self._add_task(self.alice_id, "Completed", 4, status="Completed")
        self._set_preferences(self.alice_id, task_enabled=1)

        with patch(
            "services.notification_service.send_email",
            return_value=(True, None),
        ) as send:
            self._process(self.now.replace(hour=8))
            self.assertEqual(send.call_count, 1)
            self.assertEqual(
                send.call_args.args[1],
                "alice-mail@example.test",
            )
            self.assertEqual(
                send.call_args.args[2],
                "Task Reminder – Student Attendance Manager",
            )
            body = send.call_args.args[3]
            self.assertIn("Task: Seven days\nStatus: Upcoming.", body)
            self.assertIn("Task: Three days\nStatus: Upcoming.", body)
            self.assertIn("Task: Due today\nStatus: Due Today.", body)
            self.assertIn("Task: Overdue\nStatus: Overdue.", body)
            self.assertNotIn("Ten days", body)
            self.assertNotIn("Completed", body)

            self._process(self.now.replace(hour=8))
            self.assertEqual(send.call_count, 1)

            with self.app.app_context():
                with get_db_connection() as connection:
                    connection.execute(
                        """
                        UPDATE tasks
                        SET status = 'Completed', completed_at = CURRENT_TIMESTAMP
                        WHERE task_id = ? AND student_id = ?
                        """,
                        (upcoming_id, self.alice_id),
                    )
            self._process(
                (self.now + timedelta(days=1)).replace(hour=8)
            )
            self.assertEqual(send.call_count, 2)
            next_day_body = send.call_args.args[3]
            self.assertNotIn("Seven days", next_day_body)
            self.assertIn("Task: Three days", next_day_body)

        logs = self._logs(self.alice_id)
        self.assertEqual(
            sum(row["notification_type"] == "task" for row in logs),
            7,
        )

    def test_disabled_notifications_and_failed_delivery_are_recorded(self):
        self._add_subject(self.alice_id, "Limited subject", 3)
        task_id = self._add_task(self.alice_id, "Upcoming task", 2)
        self._set_preferences(
            self.alice_id,
            attendance_enabled=1,
            task_enabled=1,
        )
        with patch(
            "services.notification_service.send_email",
            return_value=(False, "SMTP_AUTHENTICATION_FAILED"),
        ) as send:
            self._process(self.now)
            self.assertEqual(send.call_count, 1)
            self._process(self.now)
            self.assertEqual(send.call_count, 1)
            self._process(self.now.replace(hour=8))
            self.assertEqual(send.call_count, 2)
            self._process(self.now.replace(hour=8))
            self.assertEqual(send.call_count, 2)

        logs = self._logs(self.alice_id)
        self.assertEqual(len(logs), 2)
        self.assertTrue(all(row["status"] == "failed" for row in logs))
        self.assertTrue(
            all(
                row["error_details"] == "SMTP_AUTHENTICATION_FAILED"
                for row in logs
            )
        )
        self.assertEqual(
            {row["task_id"] for row in logs if row["notification_type"] == "task"},
            {task_id},
        )

        self._set_preferences(
            self.alice_id,
            attendance_enabled=0,
            task_enabled=0,
        )
        next_day = self.now + timedelta(days=1)
        with patch("services.notification_service.send_email") as send:
            self._process(next_day)
            self._process(next_day.replace(hour=8))
        send.assert_not_called()

    def test_updated_notification_time_is_respected(self):
        self._add_subject(self.alice_id, "Limited subject", 3)
        self._set_preferences(
            self.alice_id,
            attendance_enabled=1,
            attendance_time="07:15",
        )

        with patch(
            "services.notification_service.send_email",
            return_value=(True, None),
        ) as send:
            self._process(self.now)
            send.assert_not_called()
            self._process(self.now.replace(minute=15))

        send.assert_called_once()
        self.assertEqual(self._logs(self.alice_id)[0]["scheduled_time"], "07:15")

    def test_preferences_are_validated_persisted_and_student_scoped(self):
        dashboard = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("Notification Preferences", dashboard)
        self.assertIn("alice-mail@example.test", dashboard)
        self.assertNotIn('name="email"', dashboard)

        response = self.client.post(
            "/notifications/preferences",
            data={
                "attendance_enabled": "1",
                "attendance_time": "07:15",
                "task_time": "08:20",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            with get_db_connection() as connection:
                alice = connection.execute(
                    "SELECT * FROM notification_preferences WHERE student_id = ?",
                    (self.alice_id,),
                ).fetchone()
                bob = connection.execute(
                    "SELECT * FROM notification_preferences WHERE student_id = ?",
                    (self.bob_id,),
                ).fetchone()
        self.assertEqual(
            (
                alice["attendance_enabled"],
                alice["attendance_time"],
                alice["task_enabled"],
                alice["task_time"],
            ),
            (1, "07:15", 0, "08:20"),
        )
        self.assertEqual(
            (
                bob["attendance_enabled"],
                bob["attendance_time"],
                bob["task_enabled"],
                bob["task_time"],
            ),
            (0, "07:00", 0, "08:00"),
        )

        response = self.client.post(
            "/notifications/preferences",
            data={
                "attendance_time": "24:61",
                "task_time": "08:00",
            },
        )
        self.assertEqual(response.status_code, 302)
        page = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("07:15", page)

    def test_student_registration_receives_default_preferences(self):
        response = self.client.post(
            "/register",
            data={
                "name": "New Student",
                "usn": "MAIL003",
                "email": "new-mail@example.test",
                "password": "securepass123",
                "confirm_password": "securepass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            with get_db_connection() as connection:
                preferences = connection.execute(
                    """
                    SELECT p.attendance_enabled, p.attendance_time,
                           p.task_enabled, p.task_time
                    FROM notification_preferences p
                    JOIN students s ON s.student_id = p.student_id
                    WHERE s.usn = 'MAIL003'
                    """
                ).fetchone()
        self.assertEqual(
            tuple(preferences),
            (0, "07:00", 0, "08:00"),
        )

    def test_email_sender_uses_tls_and_reports_authentication_failure(self):
        configuration = {
            "SMTP_EMAIL": "sender@example.test",
            "SMTP_APP_PASSWORD": "test-secret",
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "587",
        }
        with patch("services.email_service.smtplib.SMTP") as smtp:
            server = smtp.return_value.__enter__.return_value
            sent, error = send_email(
                configuration,
                "student@example.test",
                "Test notification",
                "Hello",
            )
        self.assertTrue(sent)
        self.assertIsNone(error)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("sender@example.test", "test-secret")
        self.assertEqual(server.send_message.call_args.args[0]["To"], "student@example.test")

        with patch("services.email_service.smtplib.SMTP") as smtp:
            smtp.return_value.__enter__.return_value.login.side_effect = (
                smtplib.SMTPAuthenticationError(535, b"authentication failed")
            )
            sent, error = send_email(
                configuration,
                "student@example.test",
                "Test notification",
                "Hello",
            )
        self.assertFalse(sent)
        self.assertEqual(error, "SMTP_AUTHENTICATION_FAILED")

        sent, error = send_email(
            {"SMTP_EMAIL": "", "SMTP_APP_PASSWORD": ""},
            "student@example.test",
            "Test notification",
            "Hello",
        )
        self.assertFalse(sent)
        self.assertEqual(error, "SMTP_NOT_CONFIGURED")

    def test_only_one_scheduler_process_can_hold_the_database_lock(self):
        second_app = create_app(
            type(
                "SecondTestConfig",
                (Config,),
                {
                    "TESTING": True,
                    "WTF_CSRF_ENABLED": False,
                    "SECRET_KEY": "scheduler-test-key",
                    "DATABASE": self.database_path,
                    "UPLOAD_FOLDER": os.path.join(self.temp_dir.name, "other-uploads"),
                },
            )
        )
        scheduler = start_scheduler(self.app)
        self.assertIsNotNone(scheduler)
        self.assertIs(start_scheduler(self.app), scheduler)
        self.assertIsNone(start_scheduler(second_app))
        stop_scheduler(self.app)
        second_scheduler = start_scheduler(second_app)
        self.assertIsNotNone(second_scheduler)
        stop_scheduler(second_app)


if __name__ == "__main__":
    unittest.main()
