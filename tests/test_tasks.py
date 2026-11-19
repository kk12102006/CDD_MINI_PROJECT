import os
import tempfile
import unittest
from datetime import date, timedelta

from app import create_app
from config import Config
from database.db_connection import get_db_connection


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="attendance-tasks-")
        self.database_path = os.path.join(self.temp_dir.name, "test.db")
        test_config = type(
            "TestConfig",
            (Config,),
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SECRET_KEY": "tasks-test-key",
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
                    VALUES ('Alice', 'TASK001', 'alice-tasks@example.test', 'hash')
                    """
                ).lastrowid
                self.bob_id = connection.execute(
                    """
                    INSERT INTO students (name, usn, email, password_hash)
                    VALUES ('Bob', 'TASK002', 'bob-tasks@example.test', 'hash')
                    """
                ).lastrowid
                self.alice_subject_id = connection.execute(
                    """
                    INSERT INTO subjects (
                        student_id, subject_name, total_scheduled_classes,
                        minimum_percentage
                    ) VALUES (?, 'Java', 20, 75)
                    """,
                    (self.alice_id,),
                ).lastrowid
                self.bob_subject_id = connection.execute(
                    """
                    INSERT INTO subjects (
                        student_id, subject_name, total_scheduled_classes,
                        minimum_percentage
                    ) VALUES (?, 'Private subject', 20, 75)
                    """,
                    (self.bob_id,),
                ).lastrowid
        self._login_as(self.alice_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _login_as(self, student_id):
        with self.client.session_transaction() as browser_session:
            browser_session["student_id"] = student_id

    def _add_task(self, title, deadline, subject_id=""):
        response = self.client.post(
            "/tasks/add",
            data={
                "title": title,
                "description": "Task notes",
                "subject_id": str(subject_id) if subject_id else "",
                "deadline": deadline.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)
        return response

    def _task(self, title):
        with self.app.app_context():
            with get_db_connection() as connection:
                return connection.execute(
                    "SELECT * FROM tasks WHERE title = ?",
                    (title,),
                ).fetchone()

    def test_creation_validates_title_and_date_and_supports_optional_subject(self):
        for data in (
            {"title": "   ", "deadline": date.today().isoformat()},
            {"title": "No deadline", "deadline": ""},
            {"title": "Invalid date", "deadline": "2026-02-31"},
            {"title": "Non-canonical date", "deadline": "2026-1-02"},
        ):
            response = self.client.post("/tasks/add", data=data)
            self.assertEqual(response.status_code, 200)

        self.assertIsNone(self._task("No deadline"))
        self.assertIsNone(self._task("Invalid date"))
        self.assertIsNone(self._task("Non-canonical date"))

        self._add_task("  General task  ", date.today() + timedelta(days=3))
        general_task = self._task("General task")
        self.assertIsNotNone(general_task)
        self.assertIsNone(general_task["subject_id"])
        self.assertEqual(general_task["status"], "Pending")
        self.assertIsNone(general_task["completed_at"])

        self._add_task(
            "Subject task",
            date.today() + timedelta(days=3),
            self.alice_subject_id,
        )
        subject_page = self.client.get("/tasks").get_data(as_text=True)
        self.assertIn("Java", subject_page)

    def test_subject_association_rejects_another_students_subject(self):
        response = self.client.post(
            "/tasks/add",
            data={
                "title": "Invalid association",
                "deadline": date.today().isoformat(),
                "subject_id": str(self.bob_subject_id),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Select a subject belonging to your account.",
            response.get_data(as_text=True),
        )
        self.assertIsNone(self._task("Invalid association"))

    def test_dashboard_uses_inclusive_seven_day_window_and_deadline_order(self):
        today = date.today()
        self._add_task("Eight days", today + timedelta(days=8))
        self._add_task("Seven days", today + timedelta(days=7))
        self._add_task("Five days", today + timedelta(days=5))
        self._add_task("Due today", today)
        self._add_task("Overdue two", today - timedelta(days=2))

        page = self.client.get("/dashboard").get_data(as_text=True)
        self.assertNotIn("Eight days", page)
        self.assertIn("Seven days", page)
        self.assertIn("Five days", page)
        self.assertIn("Due today", page)
        self.assertIn("Overdue two", page)
        self.assertIn("5 days remaining", page)
        self.assertIn("DUE TODAY", page)
        self.assertIn("OVERDUE – 2 DAYS", page)
        self.assertLess(page.index("Overdue two"), page.index("Due today"))
        self.assertLess(page.index("Due today"), page.index("Five days"))
        self.assertLess(page.index("Five days"), page.index("Seven days"))

        tasks_page = self.client.get("/tasks").get_data(as_text=True)
        self.assertIn("Overdue Tasks", tasks_page)
        self.assertIn("Pending Tasks", tasks_page)
        self.assertIn("Completed Tasks", tasks_page)

    def test_completion_and_reopening_update_timestamp_and_dashboard(self):
        deadline = date.today() + timedelta(days=5)
        self._add_task("Complete me", deadline)
        task = self._task("Complete me")

        response = self.client.post(f"/tasks/complete/{task['task_id']}")
        self.assertEqual(response.status_code, 302)
        completed = self._task("Complete me")
        self.assertEqual(completed["status"], "Completed")
        self.assertIsNotNone(completed["completed_at"])
        self.assertNotIn(
            "Complete me",
            self.client.get("/dashboard").get_data(as_text=True),
        )
        response = self.client.post(
            f"/tasks/edit/{task['task_id']}",
            data={
                "title": "Completed edit",
                "description": "",
                "subject_id": "",
                "deadline": (deadline + timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)
        completed_after_edit = self._task("Completed edit")
        self.assertEqual(completed_after_edit["status"], "Completed")
        self.assertEqual(
            completed_after_edit["completed_at"],
            completed["completed_at"],
        )
        completed_page = self.client.get("/tasks").get_data(as_text=True)
        self.assertIn("Completed edit", completed_page)
        self.assertIn("Reopen", completed_page)

        response = self.client.post(f"/tasks/reopen/{task['task_id']}")
        self.assertEqual(response.status_code, 302)
        reopened = self._task("Completed edit")
        self.assertEqual(reopened["status"], "Pending")
        self.assertIsNone(reopened["completed_at"])
        self.assertIn(
            "Completed edit",
            self.client.get("/dashboard").get_data(as_text=True),
        )

    def test_edit_recalculates_reminder_visibility_and_delete_removes_task(self):
        self._add_task("Old title", date.today() + timedelta(days=12))
        task = self._task("Old title")
        updated_deadline = date.today() + timedelta(days=2)
        response = self.client.post(
            f"/tasks/edit/{task['task_id']}",
            data={
                "title": "Updated title",
                "description": " Updated notes ",
                "subject_id": str(self.alice_subject_id),
                "deadline": updated_deadline.isoformat(),
                "status": "Pending",
            },
        )
        self.assertEqual(response.status_code, 302)

        updated = self._task("Updated title")
        self.assertIsNone(self._task("Old title"))
        self.assertEqual(updated["description"], "Updated notes")
        self.assertEqual(updated["subject_id"], self.alice_subject_id)
        self.assertEqual(updated["deadline"], updated_deadline.isoformat())
        dashboard = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("Updated title", dashboard)
        self.assertIn("2 days remaining", dashboard)

        response = self.client.post(f"/tasks/delete/{updated['task_id']}")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self._task("Updated title"))
        self.assertNotIn(
            "Updated title",
            self.client.get("/dashboard").get_data(as_text=True),
        )

    def test_task_operations_are_scoped_to_the_authenticated_student(self):
        self._add_task("Alice private task", date.today())
        task = self._task("Alice private task")
        self._login_as(self.bob_id)

        page = self.client.get("/tasks").get_data(as_text=True)
        self.assertNotIn("Alice private task", page)
        self.assertEqual(
            self.client.get(f"/tasks/edit/{task['task_id']}").status_code,
            302,
        )
        for action in ("complete", "reopen", "delete"):
            self.assertEqual(
                self.client.post(
                    f"/tasks/{action}/{task['task_id']}"
                ).status_code,
                302,
            )

        self._login_as(self.alice_id)
        unchanged = self._task("Alice private task")
        self.assertEqual(unchanged["status"], "Pending")
        self.assertIsNone(unchanged["completed_at"])


if __name__ == "__main__":
    unittest.main()
