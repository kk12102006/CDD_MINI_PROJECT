from datetime import date, datetime

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from database.db_connection import get_db_connection
from routes.auth import login_required
from services.task_service import get_student_tasks


tasks_bp = Blueprint("tasks", __name__)
VALID_TASK_STATUSES = {"Pending", "Completed"}


def _task_subjects(student_id):
    with get_db_connection() as connection:
        return connection.execute(
            """
            SELECT subject_id, subject_name
            FROM subjects
            WHERE student_id = ?
            ORDER BY subject_name COLLATE NOCASE, subject_id
            """,
            (student_id,),
        ).fetchall()


def _get_owned_task(task_id, student_id):
    with get_db_connection() as connection:
        return connection.execute(
            """
            SELECT t.task_id, t.subject_id, t.title, t.description,
                   t.deadline, t.status, t.created_at, t.completed_at,
                   s.subject_name
            FROM tasks t
            LEFT JOIN subjects s
              ON s.subject_id = t.subject_id
             AND s.student_id = t.student_id
            WHERE t.task_id = ? AND t.student_id = ?
            """,
            (task_id, student_id),
        ).fetchone()


def _form_values():
    return {
        "title": request.form.get("title", "").strip(),
        "description": request.form.get("description", "").strip(),
        "subject_id": request.form.get("subject_id", "").strip(),
        "deadline": request.form.get("deadline", "").strip(),
    }


def _validate_task(values):
    if not values["title"]:
        return "Task title is required.", None
    if len(values["title"]) > 200:
        return "Task title must be at most 200 characters.", None
    if not values["deadline"]:
        return "A deadline is required.", None

    try:
        deadline = datetime.strptime(values["deadline"], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return "Enter a valid deadline.", None
    if deadline.isoformat() != values["deadline"]:
        return "Enter a valid deadline.", None

    subject_id = None
    if values["subject_id"]:
        try:
            subject_id = int(values["subject_id"])
        except ValueError:
            return "Select a valid subject.", None
        if subject_id <= 0:
            return "Select a valid subject.", None

    return None, {
        "title": values["title"],
        "description": values["description"] or None,
        "subject_id": subject_id,
        "deadline": deadline.isoformat(),
    }


def _owns_subject(connection, student_id, subject_id):
    if subject_id is None:
        return True
    return (
        connection.execute(
            "SELECT 1 FROM subjects WHERE subject_id = ? AND student_id = ?",
            (subject_id, student_id),
        ).fetchone()
        is not None
    )


def _render_task_form(form_data):
    today = date.today()
    task_categories = _task_categories(session["student_id"], today)
    return render_template(
        "tasks.html",
        form_data=form_data,
        subjects=_task_subjects(session["student_id"]),
        **task_categories,
        today=today.isoformat(),
    )


def _task_categories(student_id, today):
    pending_tasks = []
    overdue_tasks = []
    completed_tasks = []
    for task in get_student_tasks(student_id, today):
        if task["status"] == "Completed":
            completed_tasks.append(task)
        elif task["deadline_date"] < today:
            overdue_tasks.append(task)
        else:
            pending_tasks.append(task)
    return {
        "pending_tasks": pending_tasks,
        "overdue_tasks": overdue_tasks,
        "completed_tasks": completed_tasks,
    }


@tasks_bp.route("/tasks")
@login_required
def list_tasks():
    today = date.today()

    return render_template(
        "tasks.html",
        form_data={},
        subjects=_task_subjects(session["student_id"]),
        **_task_categories(session["student_id"], today),
        today=today.isoformat(),
    )


@tasks_bp.route("/tasks/add", methods=["GET", "POST"])
@login_required
def add_task():
    if request.method == "GET":
        return _render_task_form({})

    values = _form_values()
    error, task = _validate_task(values)
    if error:
        flash(error, "danger")
        return _render_task_form(values)

    student_id = session["student_id"]
    subject_is_owned = True
    with get_db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if not _owns_subject(connection, student_id, task["subject_id"]):
            subject_is_owned = False
        else:
            connection.execute(
                """
                INSERT INTO tasks (
                    student_id, subject_id, title, description, deadline
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    student_id,
                    task["subject_id"],
                    task["title"],
                    task["description"],
                    task["deadline"],
                ),
            )
    if not subject_is_owned:
        flash("Select a subject belonging to your account.", "danger")
        return _render_task_form(values)

    flash("Task added successfully.", "success")
    return redirect(url_for("tasks.list_tasks"))


@tasks_bp.route("/tasks/edit/<int:task_id>", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    student_id = session["student_id"]
    task = _get_owned_task(task_id, student_id)
    if task is None:
        flash("Task not found or you do not have permission to edit it.", "danger")
        return redirect(url_for("tasks.list_tasks"))

    subjects = _task_subjects(student_id)
    if request.method == "GET":
        return render_template(
            "edit_task.html",
            task=task,
            subjects=subjects,
            form_data=None,
        )

    values = _form_values()
    error, updated_task = _validate_task(values)
    submitted_status = request.form.get("status", task["status"])
    if error is None and submitted_status not in VALID_TASK_STATUSES:
        error = "Choose a valid task status."
    if error:
        flash(error, "danger")
        return render_template(
            "edit_task.html",
            task=task,
            subjects=subjects,
            form_data=values | {"status": submitted_status},
        )

    task_found = True
    subject_is_owned = True
    with get_db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current_task = connection.execute(
            "SELECT status FROM tasks WHERE task_id = ? AND student_id = ?",
            (task_id, student_id),
        ).fetchone()
        if current_task is None:
            task_found = False
        else:
            if "status" not in request.form:
                submitted_status = current_task["status"]
            if not _owns_subject(connection, student_id, updated_task["subject_id"]):
                subject_is_owned = False
            else:
                connection.execute(
                    """
                    UPDATE tasks
                    SET subject_id = ?, title = ?, description = ?, deadline = ?,
                        status = ?,
                        completed_at = CASE
                            WHEN ? = 'Pending' THEN NULL
                            WHEN status = 'Pending' THEN CURRENT_TIMESTAMP
                            ELSE completed_at
                        END
                    WHERE task_id = ? AND student_id = ?
                    """,
                    (
                        updated_task["subject_id"],
                        updated_task["title"],
                        updated_task["description"],
                        updated_task["deadline"],
                        submitted_status,
                        submitted_status,
                        task_id,
                        student_id,
                    ),
                )
    if not task_found:
        flash("Task not found or you do not have permission to edit it.", "danger")
        return redirect(url_for("tasks.list_tasks"))
    if not subject_is_owned:
        flash("Select a subject belonging to your account.", "danger")
        return render_template(
            "edit_task.html",
            task=task,
            subjects=subjects,
            form_data=values | {"status": submitted_status},
        )

    flash("Task updated successfully.", "success")
    return redirect(url_for("tasks.list_tasks"))


@tasks_bp.route("/tasks/delete/<int:task_id>", methods=["POST"])
@login_required
def delete_task(task_id):
    with get_db_connection() as connection:
        result = connection.execute(
            "DELETE FROM tasks WHERE task_id = ? AND student_id = ?",
            (task_id, session["student_id"]),
        )
    if result.rowcount != 1:
        flash("Task not found or you do not have permission to delete it.", "danger")
        return redirect(url_for("tasks.list_tasks"))

    flash("Task deleted successfully.", "success")
    return redirect(url_for("tasks.list_tasks"))


@tasks_bp.route("/tasks/complete/<int:task_id>", methods=["POST"])
@login_required
def complete_task(task_id):
    with get_db_connection() as connection:
        result = connection.execute(
            """
            UPDATE tasks
            SET status = 'Completed', completed_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND student_id = ? AND status = 'Pending'
            """,
            (task_id, session["student_id"]),
        )
    if result.rowcount != 1:
        flash("Task not found or it is already completed.", "warning")
        return redirect(url_for("tasks.list_tasks"))

    flash("Task marked as completed.", "success")
    return redirect(url_for("tasks.list_tasks"))


@tasks_bp.route("/tasks/reopen/<int:task_id>", methods=["POST"])
@login_required
def reopen_task(task_id):
    with get_db_connection() as connection:
        result = connection.execute(
            """
            UPDATE tasks
            SET status = 'Pending', completed_at = NULL
            WHERE task_id = ? AND student_id = ? AND status = 'Completed'
            """,
            (task_id, session["student_id"]),
        )
    if result.rowcount != 1:
        flash("Task not found or it is already pending.", "warning")
        return redirect(url_for("tasks.list_tasks"))

    flash("Task reopened successfully.", "success")
    return redirect(url_for("tasks.list_tasks"))
