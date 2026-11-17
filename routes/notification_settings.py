from datetime import datetime

from flask import Blueprint, flash, redirect, request, session, url_for

from database.db_connection import get_db_connection
from routes.auth import login_required


notification_settings_bp = Blueprint("notification_settings", __name__)


def _valid_time(value):
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except (TypeError, ValueError):
        return False
    return parsed.strftime("%H:%M") == value


@notification_settings_bp.route(
    "/notifications/preferences", methods=["POST"]
)
@login_required
def save_notification_preferences():
    attendance_time = request.form.get("attendance_time", "").strip()
    task_time = request.form.get("task_time", "").strip()
    if not _valid_time(attendance_time) or not _valid_time(task_time):
        flash("Choose valid notification times in 24-hour format.", "danger")
        return redirect(url_for("dashboard.dashboard"))

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO notification_preferences (
                student_id, attendance_enabled, attendance_time,
                task_enabled, task_time
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (student_id) DO UPDATE SET
                attendance_enabled = excluded.attendance_enabled,
                attendance_time = excluded.attendance_time,
                task_enabled = excluded.task_enabled,
                task_time = excluded.task_time
            """,
            (
                session["student_id"],
                int(request.form.get("attendance_enabled") == "1"),
                attendance_time,
                int(request.form.get("task_enabled") == "1"),
                task_time,
            ),
        )

    flash("Notification preferences saved.", "success")
    return redirect(url_for("dashboard.dashboard"))
