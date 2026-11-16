import math
import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from database.db_connection import get_db_connection
from routes.auth import login_required


subjects_bp = Blueprint("subjects", __name__)


def _form_values():
    return {
        "subject_name": request.form.get("subject_name", "").strip(),
        "total_scheduled_classes": request.form.get(
            "total_scheduled_classes", ""
        ).strip(),
        "minimum_percentage": request.form.get("minimum_percentage", "").strip(),
    }


def _validate_subject(values):
    if not all(values.values()):
        return "Please complete every field.", None
    if len(values["subject_name"]) > 120:
        return "Subject name must be at most 120 characters.", None

    try:
        total_scheduled_classes = int(values["total_scheduled_classes"])
    except ValueError:
        return "Total scheduled classes must be a positive whole number.", None
    if total_scheduled_classes <= 0:
        return "Total scheduled classes must be greater than zero.", None
    if total_scheduled_classes > 9223372036854775807:
        return "Total scheduled classes is too large to store.", None

    try:
        minimum_percentage = float(values["minimum_percentage"])
    except ValueError:
        return "Minimum attendance percentage must be a number from 1 to 100.", None
    if not math.isfinite(minimum_percentage) or not 1 <= minimum_percentage <= 100:
        return "Minimum attendance percentage must be between 1 and 100.", None

    return None, (total_scheduled_classes, minimum_percentage)


def _get_owned_subject(subject_id):
    with get_db_connection() as connection:
        return connection.execute(
            """
            SELECT subject_id, subject_name, total_scheduled_classes,
                   minimum_percentage, created_at
            FROM subjects
            WHERE subject_id = ? AND student_id = ?
            """,
            (subject_id, session["student_id"]),
        ).fetchone()


@subjects_bp.route("/subjects")
@login_required
def list_subjects():
    with get_db_connection() as connection:
        subjects = connection.execute(
            """
            SELECT subject_id, subject_name, total_scheduled_classes,
                   minimum_percentage, created_at
            FROM subjects
            WHERE student_id = ?
            ORDER BY subject_name COLLATE NOCASE, subject_id
            """,
            (session["student_id"],),
        ).fetchall()
    return render_template("subjects.html", subjects=subjects)


@subjects_bp.route("/subjects/add", methods=["GET", "POST"])
@login_required
def add_subject():
    if request.method == "GET":
        return render_template("add_subject.html", form_data={})

    values = _form_values()
    error, parsed = _validate_subject(values)
    if error:
        flash(error, "danger")
        return render_template("add_subject.html", form_data=values)

    total_scheduled_classes, minimum_percentage = parsed
    try:
        with get_db_connection() as connection:
            duplicate = connection.execute(
                """
                SELECT 1 FROM subjects
                WHERE student_id = ? AND subject_name = ?
                """,
                (session["student_id"], values["subject_name"]),
            ).fetchone()
            if duplicate:
                flash("You have already added a subject with that name.", "danger")
                return render_template("add_subject.html", form_data=values)

            connection.execute(
                """
                INSERT INTO subjects (
                    student_id, subject_name, total_scheduled_classes,
                    minimum_percentage
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    session["student_id"],
                    values["subject_name"],
                    total_scheduled_classes,
                    minimum_percentage,
                ),
            )
    except sqlite3.IntegrityError:
        flash("You have already added a subject with that name.", "danger")
        return render_template("add_subject.html", form_data=values)

    flash("Subject added successfully.", "success")
    return redirect(url_for("subjects.list_subjects"))


@subjects_bp.route("/subjects/edit/<int:subject_id>", methods=["GET", "POST"])
@login_required
def edit_subject(subject_id):
    subject = _get_owned_subject(subject_id)
    if subject is None:
        flash("Subject not found or you do not have permission to edit it.", "danger")
        return redirect(url_for("subjects.list_subjects"))

    if request.method == "GET":
        return render_template("edit_subject.html", subject=subject)

    values = _form_values()
    error, parsed = _validate_subject(values)
    if error:
        flash(error, "danger")
        return render_template(
            "edit_subject.html", subject=subject, form_data=values
        )

    total_scheduled_classes, minimum_percentage = parsed
    try:
        with get_db_connection() as connection:
            duplicate = connection.execute(
                """
                SELECT 1 FROM subjects
                WHERE student_id = ? AND subject_name = ? AND subject_id != ?
                """,
                (session["student_id"], values["subject_name"], subject_id),
            ).fetchone()
            if duplicate:
                flash("You already have another subject with that name.", "danger")
                return render_template(
                    "edit_subject.html", subject=subject, form_data=values
                )

            result = connection.execute(
                """
                UPDATE subjects
                SET subject_name = ?, total_scheduled_classes = ?,
                    minimum_percentage = ?
                WHERE subject_id = ? AND student_id = ?
                """,
                (
                    values["subject_name"],
                    total_scheduled_classes,
                    minimum_percentage,
                    subject_id,
                    session["student_id"],
                ),
            )
            if result.rowcount != 1:
                flash(
                    "Subject not found or you do not have permission to edit it.",
                    "danger",
                )
                return redirect(url_for("subjects.list_subjects"))
    except sqlite3.IntegrityError:
        flash("You already have another subject with that name.", "danger")
        return render_template(
            "edit_subject.html", subject=subject, form_data=values
        )

    flash("Subject updated successfully.", "success")
    return redirect(url_for("subjects.list_subjects"))


@subjects_bp.route("/subjects/delete/<int:subject_id>", methods=["POST"])
@login_required
def delete_subject(subject_id):
    try:
        with get_db_connection() as connection:
            result = connection.execute(
                "DELETE FROM subjects WHERE subject_id = ? AND student_id = ?",
                (subject_id, session["student_id"]),
            )
            if result.rowcount != 1:
                flash(
                    "Subject not found or you do not have permission to delete it.",
                    "danger",
                )
                return redirect(url_for("subjects.list_subjects"))
    except sqlite3.IntegrityError:
        flash(
            "This subject is linked to other records and cannot be deleted.",
            "danger",
        )
        return redirect(url_for("subjects.list_subjects"))

    flash("Subject deleted successfully.", "success")
    return redirect(url_for("subjects.list_subjects"))