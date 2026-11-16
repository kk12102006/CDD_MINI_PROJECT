import base64
import calendar
from datetime import date, datetime
from io import BytesIO
from textwrap import fill

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from database.db_connection import get_db_connection
from services.attendance_calculator import get_subject_attendance_overview


def get_student_identity(student_id):
    with get_db_connection() as connection:
        return connection.execute(
            "SELECT name, usn FROM students WHERE student_id = ?",
            (student_id,),
        ).fetchone()


def get_overall_summary(subjects):
    total_scheduled = sum(
        subject["total_scheduled_classes"] for subject in subjects
    )
    total_completed = sum(subject["completed_classes"] for subject in subjects)
    total_present = sum(subject["present_classes"] for subject in subjects)
    total_absent = sum(subject["absent_classes"] for subject in subjects)
    total_no_class = sum(subject["no_class_entries"] for subject in subjects)
    if total_completed:
        percentage = min(100.0, round(total_present / total_completed * 100, 2))
        percentage_display = f"{percentage:.2f}%"
    else:
        percentage = None
        percentage_display = "N/A"

    return {
        "subject_count": len(subjects),
        "total_scheduled_classes": total_scheduled,
        "completed_classes": total_completed,
        "present_classes": total_present,
        "absent_classes": total_absent,
        "no_class_entries": total_no_class,
        "attendance_percentage": percentage,
        "attendance_percentage_display": percentage_display,
        "satisfactory_subjects": sum(
            subject["attendance_status"] == "satisfactory"
            for subject in subjects
        ),
        "below_required_subjects": sum(
            subject["attendance_status"] == "below_required"
            for subject in subjects
        ),
        "absence_deadline_subjects": sum(
            any(warning["code"] == "deadline" for warning in subject["warnings"])
            for subject in subjects
        ),
        "shortage_subjects": sum(
            any(warning["code"] == "shortage" for warning in subject["warnings"])
            for subject in subjects
        ),
    }


def get_report_overview(student_id):
    student = get_student_identity(student_id)
    subjects = get_subject_attendance_overview(student_id)
    return {
        "student": student,
        "subjects": subjects,
        "summary": get_overall_summary(subjects),
    }


def _parse_iso_date(value):
    if not value:
        return None, None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None, "Enter dates using the YYYY-MM-DD format."
    if parsed.isoformat() != value:
        return None, "Enter dates using the YYYY-MM-DD format."
    if parsed > date.today():
        return None, "Report dates cannot be in the future."
    return parsed, None


def parse_report_filters(args, student_id):
    filters = {
        "subject_id": None,
        "month": None,
        "year": None,
        "start_date": None,
        "end_date": None,
        "status": None,
    }

    raw_subject_id = args.get("subject_id", "").strip()
    if raw_subject_id:
        try:
            subject_id = int(raw_subject_id)
        except ValueError:
            return None, "Select a valid subject."
        with get_db_connection() as connection:
            owns_subject = connection.execute(
                "SELECT 1 FROM subjects WHERE subject_id = ? AND student_id = ?",
                (subject_id, student_id),
            ).fetchone()
        if owns_subject is None:
            return None, "Select a subject belonging to your account."
        filters["subject_id"] = subject_id

    raw_month = args.get("month", "").strip()
    if raw_month:
        try:
            month = int(raw_month)
        except ValueError:
            return None, "Choose a month from 1 to 12."
        if not 1 <= month <= 12:
            return None, "Choose a month from 1 to 12."
        filters["month"] = month

    raw_year = args.get("year", "").strip()
    if raw_year:
        try:
            year = int(raw_year)
        except ValueError:
            return None, "Choose a valid report year."
        if not 1900 <= year <= date.today().year:
            return None, "Choose a year between 1900 and the current year."
        filters["year"] = year
    elif filters["month"] is not None:
        filters["year"] = date.today().year

    start_date, error = _parse_iso_date(args.get("start_date", "").strip())
    if error:
        return None, error
    end_date, error = _parse_iso_date(args.get("end_date", "").strip())
    if error:
        return None, error
    if start_date and end_date and start_date > end_date:
        return None, "Start date must not be later than end date."
    filters["start_date"] = start_date.isoformat() if start_date else None
    filters["end_date"] = end_date.isoformat() if end_date else None

    status = args.get("status", "").strip().upper()
    if status:
        if status not in {"P", "A", "NA"}:
            return None, "Select a valid attendance status."
        filters["status"] = status

    return filters, None


def get_attendance_records(student_id, filters=None):
    filters = filters or {}
    query = """
        SELECT ar.attendance_id, ar.attendance_date, ar.status,
               te.timetable_id, te.period_number, te.start_time, te.end_time,
               s.subject_id, s.subject_name
        FROM attendance_records ar
        JOIN timetable_entries te
          ON te.timetable_id = ar.timetable_id
         AND te.student_id = ar.student_id
        JOIN subjects s
          ON s.subject_id = te.subject_id
         AND s.student_id = te.student_id
        WHERE ar.student_id = ?
    """
    parameters = [student_id]
    if filters.get("subject_id") is not None:
        query += " AND s.subject_id = ?"
        parameters.append(filters["subject_id"])
    if filters.get("start_date"):
        query += " AND ar.attendance_date >= ?"
        parameters.append(filters["start_date"])
    if filters.get("end_date"):
        query += " AND ar.attendance_date <= ?"
        parameters.append(filters["end_date"])
    if filters.get("month") is not None and filters.get("year") is not None:
        first_date = date(filters["year"], filters["month"], 1)
        last_day = calendar.monthrange(filters["year"], filters["month"])[1]
        last_date = date(filters["year"], filters["month"], last_day)
        query += " AND ar.attendance_date BETWEEN ? AND ?"
        parameters.extend((first_date.isoformat(), last_date.isoformat()))
    elif filters.get("year") is not None:
        query += " AND ar.attendance_date BETWEEN ? AND ?"
        parameters.extend(
            (f"{filters['year']:04d}-01-01", f"{filters['year']:04d}-12-31")
        )
    if filters.get("status"):
        query += " AND ar.status = ?"
        parameters.append(filters["status"])
    query += """
        ORDER BY ar.attendance_date DESC, te.start_time, te.timetable_id
    """

    with get_db_connection() as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [
        {
            **dict(row),
            "day_name": date.fromisoformat(row["attendance_date"]).strftime("%A"),
        }
        for row in rows
    ]


def get_monthly_attendance(student_id, year, month, subject_id=None):
    filters = {
        "subject_id": subject_id,
        "year": year,
        "month": month,
    }
    records = get_attendance_records(student_id, filters)
    present = sum(record["status"] == "P" for record in records)
    absent = sum(record["status"] == "A" for record in records)
    no_class = sum(record["status"] == "NA" for record in records)
    completed = present + absent
    percentage = (
        min(100.0, round(present / completed * 100, 2))
        if completed
        else None
    )
    return {
        "year": year,
        "month": month,
        "month_name": calendar.month_name[month],
        "subject_id": subject_id,
        "present_classes": present,
        "absent_classes": absent,
        "no_class_entries": no_class,
        "completed_classes": completed,
        "attendance_percentage": percentage,
        "attendance_percentage_display": (
            f"{percentage:.2f}%" if percentage is not None else "N/A"
        ),
        "records": records,
    }


def get_monthly_series(student_id, year, subject_id=None):
    first_date = f"{year:04d}-01-01"
    last_date = f"{year:04d}-12-31"
    query = """
        SELECT CAST(strftime('%m', ar.attendance_date) AS INTEGER) AS month,
               SUM(CASE WHEN ar.status = 'P' THEN 1 ELSE 0 END) AS present,
               SUM(CASE WHEN ar.status = 'A' THEN 1 ELSE 0 END) AS absent,
               SUM(CASE WHEN ar.status = 'NA' THEN 1 ELSE 0 END) AS no_class
        FROM attendance_records ar
        JOIN timetable_entries te
          ON te.timetable_id = ar.timetable_id
         AND te.student_id = ar.student_id
        JOIN subjects s
          ON s.subject_id = te.subject_id
         AND s.student_id = te.student_id
        WHERE ar.student_id = ?
          AND ar.attendance_date BETWEEN ? AND ?
    """
    parameters = [student_id, first_date, last_date]
    if subject_id is not None:
        query += " AND s.subject_id = ?"
        parameters.append(subject_id)
    query += " GROUP BY month ORDER BY month"

    with get_db_connection() as connection:
        rows = connection.execute(query, parameters).fetchall()
    monthly_data = {
        row["month"]: {
            "present": row["present"],
            "absent": row["absent"],
            "no_class": row["no_class"],
        }
        for row in rows
    }
    series = []
    for month in range(1, 13):
        counts = monthly_data.get(
            month, {"present": 0, "absent": 0, "no_class": 0}
        )
        completed = counts["present"] + counts["absent"]
        percentage = (
            min(100.0, round(counts["present"] / completed * 100, 2))
            if completed
            else None
        )
        series.append(
            {
                "month": month,
                "month_name": calendar.month_abbr[month],
                "present": counts["present"],
                "absent": counts["absent"],
                "no_class": counts["no_class"],
                "completed": completed,
                "percentage": percentage,
            }
        )
    return series


def get_subject_progress_series(student_id, subject_id):
    with get_db_connection() as connection:
        records = connection.execute(
            """
            SELECT ar.attendance_date, ar.status
            FROM attendance_records ar
            JOIN timetable_entries te
              ON te.timetable_id = ar.timetable_id
             AND te.student_id = ar.student_id
            JOIN subjects s
              ON s.subject_id = te.subject_id
             AND s.student_id = te.student_id
            WHERE ar.student_id = ? AND s.subject_id = ?
            ORDER BY ar.attendance_date, te.start_time, te.timetable_id
            """,
            (student_id, subject_id),
        ).fetchall()

    present = 0
    absent = 0
    daily_progress = {}
    for record in records:
        if record["status"] == "P":
            present += 1
        elif record["status"] == "A":
            absent += 1
        else:
            continue
        completed = present + absent
        daily_progress[record["attendance_date"]] = round(
            present / completed * 100, 2
        )

    return [
        {
            "attendance_date": report_date,
            "attendance_percentage": percentage,
        }
        for report_date, percentage in daily_progress.items()
    ]


def _figure_data_uri(figure):
    image = BytesIO()
    FigureCanvasAgg(figure).print_png(image)
    figure.clear()
    return "data:image/png;base64," + base64.b64encode(image.getvalue()).decode(
        "ascii"
    )


def create_subject_attendance_chart(subjects):
    if not subjects:
        return None

    figure = Figure(
        figsize=(max(8, len(subjects) * 0.9), 4.2),
        facecolor="white",
        constrained_layout=True,
    )
    axes = figure.add_subplot(1, 1, 1)
    positions = list(range(len(subjects)))
    width = 0.36
    actual = [
        subject["attendance_percentage"]
        if subject["attendance_percentage"] is not None
        else 0
        for subject in subjects
    ]
    required = [subject["minimum_percentage"] for subject in subjects]
    actual_bars = axes.bar(
        [position - width / 2 for position in positions],
        actual,
        width,
        label="Attendance",
        color="#2864dc",
    )
    axes.bar(
        [position + width / 2 for position in positions],
        required,
        width,
        label="Minimum required",
        color="#8bb49f",
    )
    for index, bar in enumerate(actual_bars):
        subject = subjects[index]
        label = subject["attendance_percentage_display"]
        axes.annotate(
            label,
            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    axes.set_xticks(positions)
    axes.set_xticklabels(
        [fill(subject["subject_name"], 14) for subject in subjects]
    )
    axes.set_ylabel("Attendance (%)")
    axes.set_ylim(0, 112)
    axes.set_title("Subject attendance vs minimum requirement")
    axes.grid(axis="y", alpha=0.2)
    axes.set_axisbelow(True)
    axes.legend(frameon=False)
    return _figure_data_uri(figure)


def create_subject_comparison_chart(subjects):
    if not subjects:
        return None

    ordered = list(reversed(subjects))
    figure = Figure(
        figsize=(8, max(3.2, len(subjects) * 0.48)),
        facecolor="white",
        constrained_layout=True,
    )
    axes = figure.add_subplot(1, 1, 1)
    positions = list(range(len(ordered)))
    percentages = [
        item["attendance_percentage"]
        if item["attendance_percentage"] is not None
        else 0
        for item in ordered
    ]
    colors = [
        "#dc6670"
        if item["attendance_status"] == "below_required"
        else "#47a786"
        if item["attendance_status"] == "satisfactory"
        else "#aab5c4"
        for item in ordered
    ]
    bars = axes.barh(positions, percentages, color=colors, height=0.62)
    for index, bar in enumerate(bars):
        item = ordered[index]
        label = item["attendance_percentage_display"]
        axes.annotate(
            label,
            (bar.get_width(), bar.get_y() + bar.get_height() / 2),
            xytext=(5, 0),
            textcoords="offset points",
            va="center",
            fontsize=8,
        )
    axes.scatter(
        [item["minimum_percentage"] for item in ordered],
        positions,
        marker="|",
        s=180,
        linewidths=2,
        color="#253c5b",
        label="Minimum required",
        zorder=3,
    )
    axes.set_yticks(positions)
    axes.set_yticklabels([fill(item["subject_name"], 24) for item in ordered])
    axes.set_xlim(0, 112)
    axes.set_xlabel("Attendance (%)")
    axes.set_title("Subject attendance comparison")
    axes.grid(axis="x", alpha=0.2)
    axes.set_axisbelow(True)
    axes.legend(frameon=False)
    return _figure_data_uri(figure)


def create_present_absent_chart(present, absent):
    if present + absent == 0:
        return None

    figure = Figure(figsize=(5.4, 4.1), facecolor="white", constrained_layout=True)
    axes = figure.add_subplot(1, 1, 1)
    axes.pie(
        [present, absent],
        labels=[f"Present ({present})", f"Absent ({absent})"],
        colors=["#47a786", "#dc6670"],
        autopct="%1.1f%%",
        startangle=90,
        wedgeprops={"width": 0.46, "edgecolor": "white"},
        textprops={"fontsize": 9},
    )
    axes.set_title("Present vs absent classes")
    return _figure_data_uri(figure)


def create_monthly_attendance_chart(series, year, title="Monthly attendance"):
    if not series or not any(month["completed"] for month in series):
        return None

    figure = Figure(figsize=(9, 4.5), facecolor="white", constrained_layout=True)
    axes = figure.add_subplot(1, 1, 1)
    positions = list(range(len(series)))
    width = 0.36
    axes.bar(
        [position - width / 2 for position in positions],
        [month["present"] for month in series],
        width,
        label="Present",
        color="#47a786",
    )
    axes.bar(
        [position + width / 2 for position in positions],
        [month["absent"] for month in series],
        width,
        label="Absent",
        color="#dc6670",
    )
    axes.set_xticks(positions)
    axes.set_xticklabels([month["month_name"] for month in series])
    axes.set_ylabel("Completed classes")
    axes.set_title(f"{title} - {year}")
    axes.grid(axis="y", alpha=0.2)
    axes.set_axisbelow(True)

    percentage_axes = axes.twinx()
    percentage_points = [
        month["percentage"] if month["percentage"] is not None else float("nan")
        for month in series
    ]
    percentage_axes.plot(
        positions,
        percentage_points,
        color="#2864dc",
        marker="o",
        linewidth=2,
        label="Attendance percentage",
    )
    percentage_axes.set_ylabel("Attendance (%)")
    percentage_axes.set_ylim(0, 105)
    handles, labels = axes.get_legend_handles_labels()
    other_handles, other_labels = percentage_axes.get_legend_handles_labels()
    axes.legend(handles + other_handles, labels + other_labels, frameon=False)
    return _figure_data_uri(figure)


def create_attendance_progress_chart(series, subject_name, minimum_percentage):
    if not series:
        return None

    figure = Figure(figsize=(9, 4.2), facecolor="white", constrained_layout=True)
    axes = figure.add_subplot(1, 1, 1)
    dates = [
        date.fromisoformat(item["attendance_date"])
        for item in series
    ]
    percentages = [item["attendance_percentage"] for item in series]
    axes.plot(
        dates,
        percentages,
        marker="o",
        color="#2864dc",
        linewidth=2,
        label="Attendance",
    )
    axes.axhline(
        minimum_percentage,
        color="#e0a52e",
        linestyle="--",
        linewidth=1.5,
        label=f"Minimum required ({minimum_percentage:g}%)",
    )
    axes.set_ylim(0, 105)
    axes.set_ylabel("Cumulative attendance (%)")
    axes.set_title(f"{subject_name} attendance progress")
    axes.grid(alpha=0.2)
    axes.legend(frameon=False)
    figure.autofmt_xdate()
    return _figure_data_uri(figure)
