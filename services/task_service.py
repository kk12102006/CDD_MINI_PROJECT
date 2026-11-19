from datetime import date, timedelta

from database.db_connection import get_db_connection


def _task_rows(student_id, where_clause="", parameters=(), current_date=None):
    query = """
        SELECT t.task_id, t.student_id, t.subject_id, t.title, t.description,
               t.deadline, t.status, t.created_at, t.completed_at,
               s.subject_name
        FROM tasks t
        LEFT JOIN subjects s
          ON s.subject_id = t.subject_id
         AND s.student_id = t.student_id
        WHERE t.student_id = ?
    """
    if where_clause:
        query += " AND " + where_clause
    query += " ORDER BY t.deadline, t.created_at, t.task_id"

    with get_db_connection() as connection:
        rows = connection.execute(query, (student_id, *parameters)).fetchall()

    current_date = current_date or date.today()
    return [
        {
            **dict(row),
            "deadline_date": date.fromisoformat(row["deadline"]),
            "days_remaining": (
                date.fromisoformat(row["deadline"]) - current_date
            ).days,
        }
        for row in rows
    ]


def get_student_tasks(student_id, current_date=None):
    return _task_rows(student_id, current_date=current_date)


def get_remaining_tasks(student_id, current_date=None):
    current_date = current_date or date.today()
    reminder_end_date = current_date + timedelta(days=7)
    return _task_rows(
        student_id,
        "t.status = 'Pending' AND t.deadline <= ?",
        (reminder_end_date.isoformat(),),
        current_date,
    )
