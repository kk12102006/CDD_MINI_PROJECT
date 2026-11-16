import os
import re
import uuid
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from database.db_connection import get_db_connection
from routes.auth import login_required
from services.pdf_extractor import extract_timetable_from_pdf


timetable_bp = Blueprint("timetable", __name__)
DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
DAY_ORDER = {day: index for index, day in enumerate(DAYS)}


def _subject_list():
    with get_db_connection() as connection:
        return connection.execute(
            """
            SELECT subject_id, subject_name
            FROM subjects
            WHERE student_id = ?
            ORDER BY subject_name COLLATE NOCASE, subject_id
            """,
            (session["student_id"],),
        ).fetchall()


def _normalize_time(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    raw = raw.replace(".", ":")
    if re.fullmatch(r"\d{1,2}:\d{2}", raw):
        try:
            parsed = datetime.strptime(raw, "%H:%M")
            return parsed.strftime("%H:%M")
        except ValueError:
            return None
    if re.fullmatch(r"\d{1,2}:\d{2}\s*(AM|PM)", raw, re.IGNORECASE):
        try:
            parsed = datetime.strptime(raw.upper(), "%I:%M %p")
            return parsed.strftime("%H:%M")
        except ValueError:
            return None
    return None


def _minutes(value):
    normalized = _normalize_time(value)
    if normalized is None:
        raise ValueError("Time must be in HH:MM or HH:MM AM/PM format.")
    hours, minutes = map(int, normalized.split(":"))
    return hours * 60 + minutes


def _subject_lookup(subject_id):
    for subject in _subject_list():
        if subject["subject_id"] == subject_id:
            return subject
    return None


def _timetable_entries_for_student():
    with get_db_connection() as connection:
        return connection.execute(
            """
            SELECT te.timetable_id, te.day_of_week, te.start_time, te.end_time,
                   te.period_number, te.subject_id, s.subject_name
            FROM timetable_entries te
            JOIN subjects s ON s.subject_id = te.subject_id
            WHERE te.student_id = ?
            ORDER BY CASE te.day_of_week
                WHEN 'Monday' THEN 1
                WHEN 'Tuesday' THEN 2
                WHEN 'Wednesday' THEN 3
                WHEN 'Thursday' THEN 4
                WHEN 'Friday' THEN 5
                WHEN 'Saturday' THEN 6
                WHEN 'Sunday' THEN 7
                ELSE 8
            END, te.start_time, te.end_time
            """,
            (session["student_id"],),
        ).fetchall()


def _has_overlap(day_of_week, start_time, end_time, exclude_id=None):
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT timetable_id, start_time, end_time
            FROM timetable_entries
            WHERE student_id = ? AND day_of_week = ?
            """,
            (session["student_id"], day_of_week),
        ).fetchall()

    start_minutes = _minutes(start_time)
    end_minutes = _minutes(end_time)
    for row in rows:
        if exclude_id is not None and row["timetable_id"] == exclude_id:
            continue
        current_start = _minutes(row["start_time"])
        current_end = _minutes(row["end_time"])
        if start_minutes < current_end and end_minutes > current_start:
            return True
    return False


@timetable_bp.route("/timetable")
@login_required
def timetable():
    entries = _timetable_entries_for_student()
    subjects = _subject_list()
    grid = {}
    for day in DAYS:
        grid[day] = {}
    for entry in entries:
        grid.setdefault(entry["day_of_week"], {})[entry["start_time"]] = {
            "subject_name": entry["subject_name"],
            "timetable_id": entry["timetable_id"],
            "subject_id": entry["subject_id"],
            "start_time": entry["start_time"],
            "end_time": entry["end_time"],
        }
    time_slots = sorted(
        {entry["start_time"] for entry in entries},
        key=lambda slot: _minutes(slot),
    )
    return render_template(
        "timetable.html",
        days=DAYS,
        entries=entries,
        subjects=subjects,
        grid=grid,
        time_slots=time_slots,
    )


@timetable_bp.route("/timetable/upload", methods=["POST"])
@login_required
def upload_timetable():
    file = request.files.get("pdf_file")
    if file is None or file.filename == "":
        flash("Please choose a PDF file to upload.", "danger")
        return redirect(url_for("timetable.timetable"))

    filename = secure_filename(file.filename)
    extension = os.path.splitext(filename)[1].lower()
    allowed = current_app.config.get("ALLOWED_EXTENSIONS", {".pdf"})
    if extension not in allowed:
        flash("Only PDF files are supported for timetable uploads.", "danger")
        return redirect(url_for("timetable.timetable"))

    if file.mimetype and file.mimetype != "application/pdf":
        flash("The uploaded file does not appear to be a valid PDF.", "danger")
        return redirect(url_for("timetable.timetable"))

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_dir, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex}{extension}"
    file_path = os.path.join(upload_dir, unique_name)
    file.save(file_path)

    subjects = _subject_list()
    subject_names = [subject["subject_name"] for subject in subjects]
    preview_entries = extract_timetable_from_pdf(file_path, subject_names)
    if not preview_entries:
        flash("Text could not be extracted from this PDF. Please upload a text-based PDF or use manual timetable entry.", "warning")
        return redirect(url_for("timetable.timetable"))

    matched_entries = []
    for entry in preview_entries:
        matched_subject = None
        for subject in subjects:
            if subject["subject_name"].casefold() == str(entry["subject_name"]).casefold():
                matched_subject = subject
                break
        if matched_subject is not None:
            entry["subject_id"] = matched_subject["subject_id"]
            entry["subject_name"] = matched_subject["subject_name"]
        else:
            entry["subject_id"] = None
        matched_entries.append(entry)

    session["timetable_preview"] = matched_entries
    return redirect(url_for("timetable.preview_timetable"))


@timetable_bp.route("/timetable/preview")
@login_required
def preview_timetable():
    preview_entries = session.get("timetable_preview") or []
    if not preview_entries:
        flash("There is no timetable preview available yet.", "warning")
        return redirect(url_for("timetable.timetable"))
    return render_template(
        "timetable.html",
        days=DAYS,
        preview_entries=preview_entries,
        subjects=_subject_list(),
        show_preview=True,
        entries=_timetable_entries_for_student(),
    )


@timetable_bp.route("/timetable/confirm", methods=["POST"])
@login_required
def confirm_timetable_preview():
    preview_entries = session.get("timetable_preview") or []
    if not preview_entries:
        flash("There is no timetable preview to confirm.", "warning")
        return redirect(url_for("timetable.timetable"))

    subjects = {subject["subject_id"]: subject for subject in _subject_list()}
    final_entries = []
    for index in range(len(preview_entries)):
        subject_id = request.form.get(f"preview_subject_{index}")
        day = request.form.get(f"preview_day_{index}")
        start = request.form.get(f"preview_start_{index}")
        end = request.form.get(f"preview_end_{index}")
        period = request.form.get(f"preview_period_{index}")
        if day not in DAYS:
            flash("Please choose a valid day for every timetable entry.", "danger")
            return redirect(url_for("timetable.preview_timetable"))
        if not subject_id:
            flash("Please map every unmatched timetable entry to one of your subjects.", "danger")
            return redirect(url_for("timetable.preview_timetable"))
        if int(subject_id) not in subjects:
            flash("Selected subject is no longer available. Please choose a valid subject.", "danger")
            return redirect(url_for("timetable.preview_timetable"))
        try:
            start_minutes = _minutes(start)
            end_minutes = _minutes(end)
        except ValueError:
            flash("Each timetable entry needs a valid start and end time.", "danger")
            return redirect(url_for("timetable.preview_timetable"))
        if end_minutes <= start_minutes:
            flash("End time must be later than start time.", "danger")
            return redirect(url_for("timetable.preview_timetable"))
        if _has_overlap(day, start, end):
            flash("One or more entries overlap another class. Please correct the timetable before saving.", "danger")
            return redirect(url_for("timetable.preview_timetable"))
        final_entries.append(
            {
                "subject_id": int(subject_id),
                "day_of_week": day,
                "start_time": start,
                "end_time": end,
                "period_number": int(period) if period not in (None, "") else None,
            }
        )

    with get_db_connection() as connection:
        for entry in final_entries:
            connection.execute(
                """
                INSERT INTO timetable_entries (student_id, subject_id, day_of_week, start_time, end_time, period_number)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session["student_id"],
                    entry["subject_id"],
                    entry["day_of_week"],
                    entry["start_time"],
                    entry["end_time"],
                    entry["period_number"],
                ),
            )
    session.pop("timetable_preview", None)
    flash("Timetable saved successfully.", "success")
    return redirect(url_for("timetable.timetable"))


@timetable_bp.route("/timetable/manual", methods=["POST"])
@login_required
def add_manual_timetable():
    subject_id = request.form.get("subject_id")
    day_of_week = request.form.get("day_of_week")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    period_number = request.form.get("period_number", "").strip()

    if not all((subject_id, day_of_week, start_time, end_time)):
        flash("Please complete the day, subject, start time and end time fields.", "danger")
        return redirect(url_for("timetable.timetable"))
    if day_of_week not in DAYS:
        flash("Please select a valid day of the week.", "danger")
        return redirect(url_for("timetable.timetable"))
    if start_time == end_time:
        flash("End time must be later than start time.", "danger")
        return redirect(url_for("timetable.timetable"))

    try:
        subject_id = int(subject_id)
        if subject_id not in {subject["subject_id"] for subject in _subject_list()}:
            raise ValueError
    except ValueError:
        flash("The selected subject does not belong to your account.", "danger")
        return redirect(url_for("timetable.timetable"))

    try:
        start_minutes = _minutes(start_time)
        end_minutes = _minutes(end_time)
    except ValueError:
        flash("Use time values in HH:MM or HH:MM AM/PM format.", "danger")
        return redirect(url_for("timetable.timetable"))
    if end_minutes <= start_minutes:
        flash("End time must be later than start time.", "danger")
        return redirect(url_for("timetable.timetable"))
    if _has_overlap(day_of_week, start_time, end_time):
        flash("This slot overlaps an existing timetable entry. Please adjust the timings.", "danger")
        return redirect(url_for("timetable.timetable"))

    period_value = int(period_number) if period_number else None
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO timetable_entries (student_id, subject_id, day_of_week, start_time, end_time, period_number)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session["student_id"], subject_id, day_of_week, _normalize_time(start_time), _normalize_time(end_time), period_value),
        )
    flash("Timetable entry added successfully.", "success")
    return redirect(url_for("timetable.timetable"))


@timetable_bp.route("/timetable/edit/<int:timetable_id>", methods=["GET", "POST"])
@login_required
def edit_timetable_entry(timetable_id):
    with get_db_connection() as connection:
        entry = connection.execute(
            """
            SELECT te.timetable_id, te.day_of_week, te.start_time, te.end_time,
                   te.period_number, te.subject_id
            FROM timetable_entries te
            WHERE te.timetable_id = ? AND te.student_id = ?
            """,
            (timetable_id, session["student_id"]),
        ).fetchone()
    if entry is None:
        flash("The timetable entry could not be found.", "danger")
        return redirect(url_for("timetable.timetable"))

    subjects = _subject_list()
    if request.method == "GET":
        return render_template(
            "timetable.html",
            days=DAYS,
            edit_entry=entry,
            subjects=subjects,
            entries=_timetable_entries_for_student(),
        )

    subject_id = request.form.get("subject_id")
    day_of_week = request.form.get("day_of_week")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    if not all((subject_id, day_of_week, start_time, end_time)):
        flash("Please complete every timetable field.", "danger")
        return redirect(url_for("timetable.edit_timetable_entry", timetable_id=timetable_id))
    try:
        subject_id = int(subject_id)
    except ValueError:
        flash("The selected subject is invalid.", "danger")
        return redirect(url_for("timetable.edit_timetable_entry", timetable_id=timetable_id))
    if subject_id not in {subject["subject_id"] for subject in subjects}:
        flash("The selected subject does not belong to your account.", "danger")
        return redirect(url_for("timetable.edit_timetable_entry", timetable_id=timetable_id))
    try:
        if _minutes(start_time) >= _minutes(end_time):
            raise ValueError
    except ValueError:
        flash("End time must be later than start time.", "danger")
        return redirect(url_for("timetable.edit_timetable_entry", timetable_id=timetable_id))
    if _has_overlap(day_of_week, start_time, end_time, exclude_id=timetable_id):
        flash("The updated timetable entry overlaps with another class.", "danger")
        return redirect(url_for("timetable.edit_timetable_entry", timetable_id=timetable_id))

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE timetable_entries
            SET subject_id = ?, day_of_week = ?, start_time = ?, end_time = ?, period_number = ?
            WHERE timetable_id = ? AND student_id = ?
            """,
            (
                subject_id,
                day_of_week,
                _normalize_time(start_time),
                _normalize_time(end_time),
                int(request.form.get("period_number")) if request.form.get("period_number") not in (None, "") else None,
                timetable_id,
                session["student_id"],
            ),
        )
    flash("Timetable entry updated successfully.", "success")
    return redirect(url_for("timetable.timetable"))


@timetable_bp.route("/timetable/delete/<int:timetable_id>", methods=["POST"])
@login_required
def delete_timetable_entry(timetable_id):
    with get_db_connection() as connection:
        result = connection.execute(
            "DELETE FROM timetable_entries WHERE timetable_id = ? AND student_id = ?",
            (timetable_id, session["student_id"]),
        )
    if result.rowcount != 1:
        flash("The timetable entry could not be found or is not yours.", "danger")
        return redirect(url_for("timetable.timetable"))
    flash("Timetable entry deleted successfully.", "success")
    return redirect(url_for("timetable.timetable"))


@timetable_bp.route("/timetable/replace", methods=["POST"])
@login_required
def replace_timetable():
    with get_db_connection() as connection:
        connection.execute(
            "DELETE FROM timetable_entries WHERE student_id = ?",
            (session["student_id"],),
        )
    flash("Your timetable was replaced successfully.", "success")
    return redirect(url_for("timetable.timetable"))
