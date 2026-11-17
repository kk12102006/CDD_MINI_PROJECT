from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import current_app

from database.db_connection import get_db_connection
from services.attendance_calculator import get_subject_attendance_overview
from services.email_service import send_email


ATTENDANCE_EMAIL_SUBJECT = "Attendance Warning – Student Attendance Manager"
TASK_EMAIL_SUBJECT = "Task Reminder – Student Attendance Manager"


def _claim_notification(
    student_id,
    notification_type,
    task_id,
    notification_date,
    scheduled_time,
    recipient,
):
    with get_db_connection() as connection:
        result = connection.execute(
            """
            INSERT INTO notification_logs (
                student_id, notification_type, task_id, notification_date,
                scheduled_time, recipient, status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            ON CONFLICT DO NOTHING
            """,
            (
                student_id,
                notification_type,
                task_id,
                notification_date.isoformat(),
                scheduled_time,
                recipient,
            ),
        )
        return result.lastrowid if result.rowcount == 1 else None


def _finish_notification(notification_id, status, error_code=None):
    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE notification_logs
            SET status = ?, error_details = ?,
                sent_at = CASE WHEN ? = 'sent' THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE notification_id = ? AND status = 'pending'
            """,
            (status, error_code, status, notification_id),
        )


def _deliver_notification(notification_id, recipient, subject, body):
    sent, error_code = send_email(
        current_app.config,
        recipient,
        subject,
        body,
    )
    _finish_notification(
        notification_id,
        "sent" if sent else "failed",
        error_code,
    )


def _scheduled_subject_ids(student_id, current_date):
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT te.subject_id
            FROM timetable_entries te
            JOIN subjects s
              ON s.subject_id = te.subject_id
             AND s.student_id = te.student_id
            WHERE te.student_id = ? AND te.day_of_week = ?
            ORDER BY te.subject_id
            """,
            (student_id, current_date.strftime("%A")),
        ).fetchall()
    return [row["subject_id"] for row in rows]


def _attendance_warnings(student_id, current_date):
    subject_ids = _scheduled_subject_ids(student_id, current_date)
    if not subject_ids:
        return []
    overview = get_subject_attendance_overview(student_id, subject_ids)
    return [
        subject
        for subject in overview
        if subject["remaining_allowed_absences"] <= 2
    ]


def _process_attendance_notification(student, current_date, scheduled_time):
    notification_id = _claim_notification(
        student["student_id"],
        "attendance",
        None,
        current_date,
        scheduled_time,
        student["email"],
    )
    if notification_id is None:
        return

    warnings = _attendance_warnings(student["student_id"], current_date)
    if not warnings:
        _finish_notification(notification_id, "skipped")
        return

    subject_lines = []
    for subject in warnings:
        remaining = subject["remaining_allowed_absences"]
        absence_label = "absence" if remaining == 1 else "absences"
        subject_lines.append(
            f"- {subject['subject_name']} – {remaining} {absence_label} remaining."
        )
    body = (
        f"Dear {student['name']},\n\n"
        "Your attendance requires attention!\n\n"
        "The following subjects scheduled for today have limited remaining "
        "allowable absences:\n\n"
        + "\n".join(subject_lines)
        + "\n\nPlease attend these classes regularly to maintain the required "
        "attendance percentage.\n\nRegards,\nStudent Attendance Manager."
    )
    _deliver_notification(
        notification_id,
        student["email"],
        ATTENDANCE_EMAIL_SUBJECT,
        body,
    )


def _task_reminder_status(task, current_date):
    days_remaining = (date.fromisoformat(task["deadline"]) - current_date).days
    if days_remaining < 0:
        return "Overdue"
    if days_remaining == 0:
        return "Due Today"
    if days_remaining <= 7:
        return "Upcoming"
    return None


def _process_task_notifications(student, tasks, current_date, scheduled_time):
    claimed_tasks = []
    for task in tasks:
        notification_id = _claim_notification(
            student["student_id"],
            "task",
            task["task_id"],
            current_date,
            scheduled_time,
            student["email"],
        )
        if notification_id is not None:
            claimed_tasks.append((notification_id, task["task_id"]))
    if not claimed_tasks:
        return

    reminder_tasks = []
    skipped_notification_ids = []
    with get_db_connection() as connection:
        for notification_id, task_id in claimed_tasks:
            current_task = connection.execute(
                """
                SELECT title, deadline, status
                FROM tasks
                WHERE task_id = ? AND student_id = ?
                """,
                (task_id, student["student_id"]),
            ).fetchone()
            task_status = (
                _task_reminder_status(current_task, current_date)
                if current_task is not None
                and current_task["status"] == "Pending"
                else None
            )
            if task_status is None:
                skipped_notification_ids.append(notification_id)
                continue
            reminder_tasks.append(
                (notification_id, current_task, task_status)
            )

    for notification_id in skipped_notification_ids:
        _finish_notification(notification_id, "skipped")

    if not reminder_tasks:
        return

    task_sections = []
    for _, task, task_status in reminder_tasks:
        deadline_date = date.fromisoformat(task["deadline"])
        days_from_today = (deadline_date - current_date).days
        deadline = {
            -1: "Yesterday",
            0: "Today",
            1: "Tomorrow",
        }.get(days_from_today, deadline_date.strftime("%d %B %Y"))
        task_sections.append(
            "\n".join(
                (
                    f"Task: {task['title']}",
                    f"Status: {task_status}",
                    f"Deadline: {deadline}",
                )
            )
        )
    body = (
        f"Dear {student['name']},\n\n"
        "Here are your pending task reminders:\n\n"
        + "\n\n".join(task_sections)
        + "\n\nPlease complete your tasks before their deadlines.\n\n"
        "Regards,\nStudent Attendance Manager."
    )
    sent, error_code = send_email(
        current_app.config,
        student["email"],
        TASK_EMAIL_SUBJECT,
        body,
    )
    status = "sent" if sent else "failed"
    for notification_id, _, _ in reminder_tasks:
        _finish_notification(notification_id, status, error_code)


def process_due_notifications(current_time=None):
    timezone = ZoneInfo(current_app.config["NOTIFICATION_TIMEZONE"])
    if current_time is None:
        current_time = datetime.now(timezone)
    elif current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone)
    else:
        current_time = current_time.astimezone(timezone)

    current_date = current_time.date()
    scheduled_time = current_time.strftime("%H:%M")
    with get_db_connection() as connection:
        students = connection.execute(
            """
            SELECT p.student_id, p.attendance_enabled, p.attendance_time,
                   p.task_enabled, p.task_time, s.name, s.email
            FROM notification_preferences p
            JOIN students s ON s.student_id = p.student_id
            WHERE (p.attendance_enabled = 1 AND p.attendance_time <= ?)
               OR (p.task_enabled = 1 AND p.task_time <= ?)
            ORDER BY p.student_id
            """,
            (scheduled_time, scheduled_time),
        ).fetchall()

    for student in students:
        if (
            student["attendance_enabled"]
            and student["attendance_time"] <= scheduled_time
        ):
            _process_attendance_notification(
                student,
                current_date,
                student["attendance_time"],
            )
        if student["task_enabled"] and student["task_time"] <= scheduled_time:
            with get_db_connection() as connection:
                tasks = connection.execute(
                    """
                    SELECT task_id, title, deadline
                    FROM tasks
                    WHERE student_id = ?
                      AND status = 'Pending'
                      AND deadline <= ?
                    ORDER BY deadline, created_at, task_id
                    """,
                    (
                        student["student_id"],
                        (current_date + timedelta(days=7)).isoformat(),
                    ),
                ).fetchall()
            _process_task_notifications(
                student,
                tasks,
                current_date,
                student["task_time"],
            )
