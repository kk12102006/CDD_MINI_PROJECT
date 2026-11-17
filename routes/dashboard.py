from flask import Blueprint, flash, redirect, render_template, session, url_for

from database.db_connection import get_db_connection
from routes.auth import login_required
from services.report_service import get_overall_summary
from services.attendance_calculator import get_subject_attendance_overview
from services.task_service import get_remaining_tasks


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    with get_db_connection() as connection:
        student = connection.execute(
            """
            SELECT student_id, name, usn, email
            FROM students
            WHERE student_id = ?
            """,
            (session["student_id"],),
        ).fetchone()

    if student is None:
        session.clear()
        flash("Your account could not be found. Please log in again.", "warning")
        return redirect(url_for("auth.login"))

    with get_db_connection() as connection:
        subject_count = connection.execute(
            "SELECT COUNT(*) FROM subjects WHERE student_id = ?",
            (session["student_id"],),
        ).fetchone()[0]
        recent_subjects = connection.execute(
            """
            SELECT subject_id, subject_name, total_scheduled_classes,
                   minimum_percentage, created_at
            FROM subjects
            WHERE student_id = ?
            ORDER BY created_at DESC, subject_id DESC
            LIMIT 5
            """,
            (session["student_id"],),
        ).fetchall()

    attendance_summary = get_overall_summary(
        get_subject_attendance_overview(session["student_id"])
    )
    remaining_tasks = get_remaining_tasks(session["student_id"])
    return render_template(
        "dashboard.html",
        student=student,
        subject_count=subject_count,
        recent_subjects=recent_subjects,
        attendance_summary=attendance_summary,
        remaining_tasks=remaining_tasks,
    )