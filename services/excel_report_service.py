from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


_HEADER_FILL = PatternFill(fill_type="solid", fgColor="183153")
_HEADER_FONT = Font(color="FFFFFF", bold=True)


def _safe_value(value):
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(
        ("=", "+", "-", "@")
    ):
        return "'" + value
    return value


def _style_header(sheet):
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height = 30


def _fit_columns(sheet, max_width=48):
    for column in sheet.columns:
        width = max(
            len(str(cell.value)) if cell.value is not None else 0
            for cell in column
        )
        sheet.column_dimensions[get_column_letter(column[0].column)].width = min(
            max(width + 2, 12), max_width
        )


def _status_text(subject):
    status = {
        "satisfactory": "Satisfactory",
        "below_required": "Below required",
        "not_available": "No data",
    }.get(subject["attendance_status"], "No data")
    warnings = [
        "Deadline" if warning["code"] == "deadline" else "Shortage"
        for warning in subject["warnings"]
    ]
    return f"{status}; " + ", ".join(warnings) if warnings else status


def generate_overall_excel(student, summary, subjects, records):
    workbook = Workbook()
    overview = workbook.active
    overview.title = "Overall Summary"
    overview.append(["Measure", "Value"])
    overview_rows = [
        ("Student", student["name"]),
        ("USN", student["usn"]),
        ("Report generated", date.today()),
        ("Subjects", summary["subject_count"]),
        ("Scheduled classes", summary["total_scheduled_classes"]),
        ("Completed classes", summary["completed_classes"]),
        ("Present", summary["present_classes"]),
        ("Absent", summary["absent_classes"]),
        ("No class entries", summary["no_class_entries"]),
        (
            "Overall attendance",
            (
                summary["attendance_percentage"] / 100
                if summary["attendance_percentage"] is not None
                else None
            ),
        ),
        ("Subjects satisfactory", summary["satisfactory_subjects"]),
        ("Subjects below requirement", summary["below_required_subjects"]),
        ("Absence deadlines reached", summary["absence_deadline_subjects"]),
        ("Subjects with attendance shortage", summary["shortage_subjects"]),
    ]
    for row in overview_rows:
        overview.append([_safe_value(value) for value in row])
    _style_header(overview)
    overview["B4"].number_format = "yyyy-mm-dd"
    overview["B11"].number_format = "0.00%"
    overview.column_dimensions["A"].width = 38
    overview.column_dimensions["B"].width = 34

    subject_sheet = workbook.create_sheet("Subject Summary")
    subject_sheet.append(
        [
            "Subject",
            "Scheduled classes",
            "Completed classes",
            "Present",
            "Absent",
            "No class entries",
            "Attendance percentage",
            "Minimum percentage",
            "Maximum allowed absences",
            "Actual absences",
            "Remaining allowed absences",
            "Status and warnings",
        ]
    )
    for subject in subjects:
        subject_sheet.append(
            [
                _safe_value(subject["subject_name"]),
                subject["total_scheduled_classes"],
                subject["completed_classes"],
                subject["present_classes"],
                subject["absent_classes"],
                subject["no_class_entries"],
                (
                    subject["attendance_percentage"] / 100
                    if subject["attendance_percentage"] is not None
                    else None
                ),
                subject["minimum_percentage"] / 100,
                subject["maximum_allowed_absences"],
                subject["actual_absences"],
                subject["remaining_allowed_absences"],
                _safe_value(_status_text(subject)),
            ]
        )
    _style_header(subject_sheet)
    for row_number in range(2, subject_sheet.max_row + 1):
        subject_sheet.cell(row_number, 7).number_format = "0.00%"
        subject_sheet.cell(row_number, 8).number_format = "0.00%"
    _fit_columns(subject_sheet)

    records_sheet = workbook.create_sheet("Attendance Records")
    records_sheet.append(
        [
            "Date",
            "Day",
            "Subject",
            "Period",
            "Start time",
            "End time",
            "Status",
        ]
    )
    status_labels = {"P": "Present", "A": "Absent", "NA": "No class"}
    for record in records:
        records_sheet.append(
            [
                date.fromisoformat(record["attendance_date"]),
                record["day_name"],
                _safe_value(record["subject_name"]),
                record["period_number"] or "",
                record["start_time"],
                record["end_time"],
                status_labels[record["status"]],
            ]
        )
    _style_header(records_sheet)
    for row_number in range(2, records_sheet.max_row + 1):
        records_sheet.cell(row_number, 1).number_format = "yyyy-mm-dd"
    _fit_columns(records_sheet)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
