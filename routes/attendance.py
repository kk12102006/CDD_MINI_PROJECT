from datetime import date, datetime

from flask import Blueprint,flash, redirect, render_template, request, session, url_for

from database.db_connection import get_db_connection
from routes.auth import login_required
from services.attendance_calculator import get_subject_attendance_overview


attendance_bp = Blueprint("attendance", __name__)
VALID_STATUSES = {"P", "A", "NA"}
COMPLETED_STATUSES = {"P", "A"}



@attendance_bp.route("/attendance/overview")
@login_required
def attendance_overview():
    subjects = get_subject_attendance_overview(session["student_id"])
    return render_template(
        "attendance_overview.html" ,
        subjects=subjects,
    )


def _parse_attendance_date(raw_value, default_today=True):
    if raw_value is None and default_today:
        return date.today(), None
    try:
        parsed_date = datetime.strptime(raw_value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None, "Choose a valid attendance date."
    if parsed_date.isoformat() != raw_value:
        return None, "Choose a valid attendance date."
    if parsed_date > date.today():
        return None, "Attendance cannot be marked for a future date."
    return parsed_date, None


def _scheduled_periods(connection, student_id, attendance_date):
    weekday = attendance_date.strftime("%A")
    return connection.execute(
        """
        SELECT te.timetable_id, te.subject_id, te.day_of_week,
               te.start_time, te.end_time, te.period_number,
               s.subject_name, s.total_scheduled_classes,
               ar.attendance_id, ar.status AS attendance_status
        FROM timetable_entries te
        JOIN subjects s
          ON s.subject_id = te.subject_id
         AND s.student_id = te.student_id
        LEFT JOIN attendance_records ar
          ON ar.timetable_id = te.timetable_id
         AND ar.student_id = te.student_id
         AND ar.attendance_date = ?
        WHERE te.student_id = ? AND te.day_of_week = ?
        ORDER BY te.start_time, te.end_time, te.timetable_id
        """,
        (attendance_date.isoformat(), student_id, weekday),
    ).fetchall()


@attendance_bp.route("/attendance", methods=["GET"])
@login_required
def daily_attendance():
    selected_date, error = _parse_attendance_date(request.args.get("date"))
    if error:
        flash(error, "danger")
        return redirect(url_for("attendance.daily_attendance"))

    with get_db_connection() as connection:
        periods = _scheduled_periods(
            connection, session["student_id"], selected_date
        )

    return render_template(
        "attendance.html",
        periods=periods,
        selected_date=selected_date.isoformat(),
        today=date.today().isoformat(),
        today_display=date.today().strftime("%d-%m-%Y"),
        today_weekday=date.today().strftime("%A"),
        weekday=selected_date.strftime("%A"),
    )


@attendance_bp.route("/attendance/save", methods=["POST"])
@login_required
def save_daily_attendance():
    selected_date, error = _parse_attendance_date(
        request.form.get("attendance_date"), default_today=False
    )
    if error:
        flash(error, "danger")
        return redirect(url_for("attendance.daily_attendance"))

    student_id = session["student_id"]
    skipped = []
    saved_count = 0
    with get_db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        periods = _scheduled_periods(connection, student_id, selected_date)
        if not periods:
            flash(
                "There are no timetable periods scheduled for that date.",
                "warning",
            )
            return redirect(
                url_for(
                    "attendance.daily_attendance",
                    date=selected_date.isoformat(),
                )
            )

        submitted_statuses = {}
        for period in periods:
            field_name = f"status_{period['timetable_id']}"
            values = request.form.getlist(field_name)
            if len(values) != 1 or values[0] not in VALID_STATUSES:
                flash(
                    "Choose P, A or NA for every scheduled period.",
                    "danger",
                )
                return redirect(
                    url_for(
                        "attendance.daily_attendance",
                        date=selected_date.isoformat(),
                    )
                )
            submitted_statuses[period["timetable_id"]] = values[0]

        completed_counts = {
            row["subject_id"]: row["completed_count"]
            for row in connection.execute(
                """
                SELECT te.subject_id, COUNT(*) AS completed_count
                FROM attendance_records ar
                JOIN timetable_entries te
                  ON te.timetable_id = ar.timetable_id
                 AND te.student_id = ar.student_id
                WHERE ar.student_id = ? AND ar.status IN ('P', 'A')
                GROUP BY te.subject_id
                """,
                (student_id,),
            ).fetchall()
        }

        for period in periods:
            timetable_id = period["timetable_id"]
            new_status = submitted_statuses[timetable_id]
            old_status = period["attendance_status"]
            subject_id = period["subject_id"]
            current_count = completed_counts.get(subject_id, 0)
            projected_count = (
                current_count
                - int(old_status in COMPLETED_STATUSES)
                + int(new_status in COMPLETED_STATUSES)
            )
            if (
                new_status in COMPLETED_STATUSES
                and old_status not in COMPLETED_STATUSES
                and projected_count > period["total_scheduled_classes"]
            ):
                skipped.append(
                    (
                        period["subject_name"],
                        period["total_scheduled_classes"],
                    )
                )
                continue

            connection.execute(
                """
                INSERT INTO attendance_records (
                    student_id, timetable_id, attendance_date, status
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT (timetable_id, attendance_date)
                DO UPDATE SET
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    student_id,
                    timetable_id,
                    selected_date.isoformat(),
                    new_status,
                ),
            )
            completed_counts[subject_id] = projected_count
            saved_count += 1

    if saved_count:
        flash(
            f"Attendance saved for {selected_date.strftime('%d-%m-%Y')}.",
            "success",
        )
    for subject_name, maximum in skipped:
        flash(
            f"{subject_name} - Maximum number of classes ({maximum}) reached. "
            "Attendance marking skipped.",
            "warning",
        )
    return redirect(
        url_for("attendance.daily_attendance", date=selected_date.isoformat())
    )


@attendance_bp.route("/attendance/history")
@login_required
def attendance_history():
    raw_date = request.args.get("date") or None
    selected_date = None
    if raw_date is not None:
        selected_date, error = _parse_attendance_date(
            raw_date, default_today=False
        )
        if error:
            flash(error, "danger")
            return redirect(url_for("attendance.attendance_history"))

    query = """
        SELECT ar.attendance_id, ar.attendance_date, ar.status,
               te.timetable_id, te.start_time, te.end_time, te.period_number,
               s.subject_name
        FROM attendance_records ar
        JOIN timetable_entries te
          ON te.timetable_id = ar.timetable_id
         AND te.student_id = ar.student_id
        JOIN subjects s
          ON s.subject_id = te.subject_id
         AND s.student_id = te.student_id
        WHERE ar.student_id = ?
    """
    parameters = [session["student_id"]]
    if selected_date is not None:
        query += " AND ar.attendance_date = ?"
        parameters.append(selected_date.isoformat())
    query += """
        ORDER BY ar.attendance_date DESC, te.start_time, te.timetable_id
    """

    with get_db_connection() as connection:
        records = connection.execute(query, parameters).fetchall()

    return render_template(
        "attendance_history.html",
        records=records,
        selected_date=selected_date.isoformat() if selected_date else "",
        today=date.today().isoformat(),
        date_filter_applied=selected_date is not None,
    )


@attendance_bp.route("/attendance/edit/<int:attendance_id>", methods=["GET", "POST"])
@login_required
def edit_attendance(attendance_id):
    student_id = session["student_id"]
    with get_db_connection() as connection:
        record = connection.execute(
            """
            SELECT ar.attendance_id, ar.attendance_date, ar.status,
                   te.subject_id, te.start_time, te.end_time,
                   s.subject_name, s.total_scheduled_classes
            FROM attendance_records ar
            JOIN timetable_entries te
              ON te.timetable_id = ar.timetable_id
             AND te.student_id = ar.student_id
            JOIN subjects s
              ON s.subject_id = te.subject_id
             AND s.student_id = te.student_id
            WHERE ar.attendance_id = ? AND ar.student_id = ?
            """,
            (attendance_id, student_id),
        ).fetchone()

    if record is None:
        flash("Attendance record not found.", "danger")
        return redirect(url_for("attendance.attendance_history"))

    record_date, error = _parse_attendance_date(
        record["attendance_date"], default_today=False
    )
    if error or record_date is None:
        flash("Attendance cannot be edited for a future date.", "danger")
        return redirect(url_for("attendance.attendance_history"))

    if request.method == "GET":
        return render_template(
            "edit_attendance.html",
            record=record,
            today=date.today().isoformat(),
        )

    status_values = request.form.getlist("status")
    if len(status_values) != 1 or status_values[0] not in VALID_STATUSES:
        flash("Choose a valid attendance status.", "danger")
        return redirect(
            url_for("attendance.edit_attendance", attendance_id=attendance_id)
        )
    new_status = status_values[0]

    with get_db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current_record = connection.execute(
            """
            SELECT ar.status, te.subject_id
            FROM attendance_records ar
            JOIN timetable_entries te
              ON te.timetable_id = ar.timetable_id
             AND te.student_id = ar.student_id
            WHERE ar.attendance_id = ? AND ar.student_id = ?
            """,
            (attendance_id, student_id),
        ).fetchone()
        if current_record is None:
            flash("Attendance record not found.", "danger")
            return redirect(url_for("attendance.attendance_history"))

        if (
            new_status in COMPLETED_STATUSES
            and current_record["status"] not in COMPLETED_STATUSES
        ):
            completed_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM attendance_records ar
                JOIN timetable_entries te
                  ON te.timetable_id = ar.timetable_id
                 AND te.student_id = ar.student_id
                WHERE ar.student_id = ?
                  AND te.subject_id = ?
                  AND ar.status IN ('P', 'A')
                """,
                (student_id, current_record["subject_id"]),
            ).fetchone()[0]
            if completed_count >= record["total_scheduled_classes"]:
                flash(
                    f"{record['subject_name']} - Maximum number of classes "
                    f"({record['total_scheduled_classes']}) reached. "
                    "Attendance status was not changed.",
                    "warning",
                )
                return redirect(
                    url_for("attendance.edit_attendance", attendance_id=attendance_id)
                )

        connection.execute(
            """
            UPDATE attendance_records
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE attendance_id = ? AND student_id = ?
            """,
            (new_status, attendance_id, student_id),
        )

    flash("Attendance updated successfully.", "success")
    return redirect(
        url_for(
            "attendance.attendance_history",
            date=record["attendance_date"],
        )
    )
