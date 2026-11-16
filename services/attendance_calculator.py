import math
from decimal import Decimal

from database.db_connection import get_db_connection


def calculate_subject_attendance(subject, counts):
    present_classes = int(counts.get("present", 0))
    absent_classes = int(counts.get("absent", 0))
    no_class_entries = int(counts.get("no_class", 0))
    completed_classes = present_classes + absent_classes
    total_scheduled_classes = int(subject["total_scheduled_classes"])
    minimum_percentage = float(subject["minimum_percentage"])

    if completed_classes:
        attendance_percentage = min(
            100.0,
            round(present_classes / completed_classes * 100, 2),
        )
        attendance_percentage_display = f"{attendance_percentage:.2f}%"
        if attendance_percentage >= minimum_percentage:
            attendance_status = "satisfactory"
            attendance_status_label = "Attendance Satisfactory"
        else:
            attendance_status = "below_required"
            attendance_status_label = "Attendance Below Required Percentage"
    else:
        attendance_percentage = None
        attendance_percentage_display = "N/A"
        attendance_status = "not_available"
        attendance_status_label = "Attendance Not Yet Available"

    maximum_allowed_absences = math.floor(
        Decimal(total_scheduled_classes)
        * (Decimal("100") - Decimal(str(minimum_percentage)))
        / Decimal("100")
    )
    remaining_allowed_absences = max(
        0, maximum_allowed_absences - absent_classes
    )

    warnings = []
    if remaining_allowed_absences == 0:
        warnings.append(
            {
                "code": "deadline",
                "title": "ABSENT DEADLINE REACHED",
                "message": "You have reached the maximum number of classes you may miss.",
            }
        )
    if absent_classes > maximum_allowed_absences:
        warnings.append(
            {
                "code": "shortage",
                "title": "ATTENDANCE SHORTAGE",
                "message": "Your absences exceed the maximum permitted number.",
            }
        )

    return {
        "subject_id": subject["subject_id"],
        "subject_name": subject["subject_name"],
        "total_scheduled_classes": total_scheduled_classes,
        "completed_classes": completed_classes,
        "present_classes": present_classes,
        "absent_classes": absent_classes,
        "no_class_entries": no_class_entries,
        "attendance_percentage": attendance_percentage,
        "attendance_percentage_display": attendance_percentage_display,
        "minimum_percentage": minimum_percentage,
        "maximum_allowed_absences": maximum_allowed_absences,
        "actual_absences": absent_classes,
        "remaining_allowed_absences": remaining_allowed_absences,
        "warnings": warnings,
        "attendance_status": attendance_status,
        "attendance_status_label": attendance_status_label,
        "progress_percentage": attendance_percentage or 0,
    }


def get_subject_attendance_overview(student_id):
    with get_db_connection() as connection:
        subjects = connection.execute(
            """
            SELECT subject_id, subject_name, total_scheduled_classes,
                   minimum_percentage
            FROM subjects
            WHERE student_id = ?
            ORDER BY subject_name COLLATE NOCASE, subject_id
            """,
            (student_id,),
        ).fetchall()
        counts_by_subject = {
            row["subject_id"]: {
                "present": row["present_classes"],
                "absent": row["absent_classes"],
                "no_class": row["no_class_entries"],
            }
            for row in connection.execute(
                """
                SELECT te.subject_id,
                       SUM(CASE WHEN ar.status = 'P' THEN 1 ELSE 0 END)
                           AS present_classes,
                       SUM(CASE WHEN ar.status = 'A' THEN 1 ELSE 0 END)
                           AS absent_classes,
                       SUM(CASE WHEN ar.status = 'NA' THEN 1 ELSE 0 END)
                           AS no_class_entries
                FROM attendance_records ar
                JOIN timetable_entries te
                  ON te.timetable_id = ar.timetable_id
                 AND te.student_id = ar.student_id
                JOIN subjects s
                  ON s.subject_id = te.subject_id
                 AND s.student_id = te.student_id
                WHERE ar.student_id = ?
                GROUP BY te.subject_id
                """,
                (student_id,),
            ).fetchall()
        }

    return [
        calculate_subject_attendance(
            subject,
            counts_by_subject.get(
                subject["subject_id"],
                {"present": 0, "absent": 0, "no_class": 0},
            ),
        )
        for subject in subjects
    ]