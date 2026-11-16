import base64
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape


_NAVY = colors.HexColor("#183153")
_LIGHT_GRAY = colors.HexColor("#f3f5f8")
_MUTED = colors.HexColor("#637083")


def _styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=_NAVY,
            alignment=TA_CENTER,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportSubtitle",
            parent=styles["Normal"],
            fontSize=9,
            leading=13,
            textColor=_MUTED,
            alignment=TA_CENTER,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading2"],
            fontSize=12,
            leading=16,
            textColor=_NAVY,
            spaceBefore=10,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableCell",
            parent=styles["BodyText"],
            fontSize=7,
            leading=9,
            spaceAfter=0,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableHeader",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=8,
            textColor=colors.white,
            alignment=TA_CENTER,
        )
    )
    return styles


def _cell(value, style):
    return Paragraph(escape(str(value)), style)


def _add_footer(canvas, document):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#dce2ea"))
    canvas.line(36, 31, letter[0] - 36, 31)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(_MUTED)
    canvas.drawString(36, 19, "Student Attendance Manager")
    canvas.drawRightString(letter[0] - 36, 19, f"Page {document.page}")
    canvas.restoreState()


def _chart_image(data_uri, width=7.0 * inch, height=3.45 * inch):
    if not data_uri:
        return None
    encoded = data_uri.split(",", 1)[1]
    image = Image(BytesIO(base64.b64decode(encoded)), width=width, height=height)
    image.hAlign = "CENTER"
    return image


def _subject_status(subject):
    status = {
        "satisfactory": "Satisfactory",
        "below_required": "Below required",
        "not_available": "No data",
    }.get(subject["attendance_status"], "No data")
    warning_names = [
        "Deadline" if warning["code"] == "deadline" else "Shortage"
        for warning in subject["warnings"]
    ]
    return f"{status}; " + ", ".join(warning_names) if warning_names else status


def _summary_table(summary):
    data = [
        ["Measure", "Value", "Measure", "Value"],
        [
            "Subjects",
            str(summary["subject_count"]),
            "Overall attendance",
            summary["attendance_percentage_display"],
        ],
        [
            "Scheduled classes",
            str(summary["total_scheduled_classes"]),
            "Completed classes",
            str(summary["completed_classes"]),
        ],
        [
            "Present",
            str(summary["present_classes"]),
            "Absent",
            str(summary["absent_classes"]),
        ],
        [
            "No class entries",
            str(summary["no_class_entries"]),
            "Below requirement",
            str(summary["below_required_subjects"]),
        ],
        [
            "Absence deadlines reached",
            str(summary["absence_deadline_subjects"]),
            "Attendance shortages",
            str(summary["shortage_subjects"]),
        ],
    ]
    table = Table(data, colWidths=[1.55 * inch, 1.05 * inch, 1.65 * inch, 1.2 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 1), (-1, -1), _LIGHT_GRAY),
                ("TEXTCOLOR", (0, 1), (0, -1), _MUTED),
                ("TEXTCOLOR", (2, 1), (2, -1), _MUTED),
                ("FONTNAME", (1, 1), (1, -1), "Helvetica-Bold"),
                ("FONTNAME", (3, 1), (3, -1), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_LIGHT_GRAY, colors.white]),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#dce2ea")),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dce2ea")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _subjects_table(subjects, styles):
    headings = [
        "Subject",
        "Scheduled",
        "Done",
        "P",
        "A",
        "NA",
        "Att %",
        "Min %",
        "Max abs",
        "Left",
        "Status",
    ]
    data = [[_cell(value, styles["TableHeader"]) for value in headings]]
    for subject in subjects:
        values = [
            subject["subject_name"],
            subject["total_scheduled_classes"],
            subject["completed_classes"],
            subject["present_classes"],
            subject["absent_classes"],
            subject["no_class_entries"],
            subject["attendance_percentage_display"],
            f'{subject["minimum_percentage"]:g}%',
            subject["maximum_allowed_absences"],
            subject["remaining_allowed_absences"],
            _subject_status(subject),
        ]
        data.append([_cell(value, styles["TableCell"]) for value in values])
    table = Table(
        data,
        colWidths=[1.12 * inch, 0.55 * inch, 0.43 * inch, 0.28 * inch,
                   0.28 * inch, 0.3 * inch, 0.48 * inch, 0.45 * inch,
                   0.48 * inch, 0.4 * inch, 1.04 * inch],
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT_GRAY]),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#dce2ea")),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dce2ea")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def generate_overall_pdf(student, summary, subjects, charts=None):
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=42,
        bottomMargin=42,
        title="Student Attendance Report",
        author="Student Attendance Manager",
    )
    styles = _styles()
    story = [
        Paragraph("Student Attendance Report", styles["ReportTitle"]),
        Paragraph(
            f'{escape(student["name"])} ({escape(student["usn"])}) &nbsp;&bull;&nbsp; '
            f"Generated {date.today().strftime('%d %B %Y')}",
            styles["ReportSubtitle"],
        ),
        Paragraph("Overall summary", styles["SectionHeading"]),
        _summary_table(summary),
        Spacer(1, 10),
    ]
    charts = charts or {}
    chart = _chart_image(charts.get("subject_attendance"))
    if chart:
        story.extend(
            [
                Paragraph("Subject attendance comparison", styles["SectionHeading"]),
                chart,
                Spacer(1, 8),
            ]
        )
    story.extend(
        [
            Paragraph("Subject-wise details", styles["SectionHeading"]),
            _subjects_table(subjects, styles),
        ]
    )
    document.build(story, onFirstPage=_add_footer, onLaterPages=_add_footer)
    return output.getvalue()


def generate_subject_pdf(student, subject, records, progress_chart=None):
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=42,
        leftMargin=42,
        topMargin=42,
        bottomMargin=42,
        title=f'{subject["subject_name"]} Attendance Report',
        author="Student Attendance Manager",
    )
    styles = _styles()
    story = [
        Paragraph(
            f'{escape(subject["subject_name"])} Attendance Report',
            styles["ReportTitle"],
        ),
        Paragraph(
            f'{escape(student["name"])} ({escape(student["usn"])}) &nbsp;&bull;&nbsp; '
            f"Generated {date.today().strftime('%d %B %Y')}",
            styles["ReportSubtitle"],
        ),
        Paragraph("Attendance summary", styles["SectionHeading"]),
        _summary_table(
            {
                "subject_count": 1,
                "attendance_percentage_display": subject[
                    "attendance_percentage_display"
                ],
                "total_scheduled_classes": subject["total_scheduled_classes"],
                "completed_classes": subject["completed_classes"],
                "present_classes": subject["present_classes"],
                "absent_classes": subject["absent_classes"],
                "no_class_entries": subject["no_class_entries"],
                "below_required_subjects": int(
                    subject["attendance_status"] == "below_required"
                ),
                "absence_deadline_subjects": sum(
                    warning["code"] == "deadline" for warning in subject["warnings"]
                ),
                "shortage_subjects": sum(
                    warning["code"] == "shortage" for warning in subject["warnings"]
                ),
            },
        ),
        Spacer(1, 10),
        Paragraph(
            f'<b>Status:</b> {escape(subject["attendance_status_label"])}',
            styles["Normal"],
        ),
        Paragraph(
            f'Minimum attendance: {subject["minimum_percentage"]:g}% &nbsp;'
            f'| Maximum absences: {subject["maximum_allowed_absences"]} &nbsp;'
            f'| Remaining absences: {subject["remaining_allowed_absences"]}',
            styles["Normal"],
        ),
        Spacer(1, 8),
    ]
    for warning in subject["warnings"]:
        story.append(
            Paragraph(
                f'<b>{escape(warning["title"])}:</b> {escape(warning["message"])}',
                styles["Normal"],
            )
        )
    if subject["warnings"]:
        story.append(Spacer(1, 8))
    chart = _chart_image(progress_chart, width=6.7 * inch, height=3.1 * inch)
    if chart:
        story.extend(
            [
                Paragraph("Attendance progress", styles["SectionHeading"]),
                chart,
                Spacer(1, 8),
            ]
        )

    heading = ["Date", "Day", "Period", "Time", "Status"]
    data = [[_cell(value, styles["TableHeader"]) for value in heading]]
    for record in records:
        status = {"P": "Present", "A": "Absent", "NA": "No class"}[
            record["status"]
        ]
        data.append(
            [
                _cell(record["attendance_date"], styles["TableCell"]),
                _cell(record["day_name"], styles["TableCell"]),
                _cell(record["period_number"] or "-", styles["TableCell"]),
                _cell(
                    f'{record["start_time"]} - {record["end_time"]}',
                    styles["TableCell"],
                ),
                _cell(status, styles["TableCell"]),
            ]
        )
    if not records:
        data.append(
            [
                _cell("No attendance records found.", styles["TableCell"]),
                "",
                "",
                "",
                "",
            ]
        )
    records_table = Table(
        data,
        colWidths=[1.0 * inch, 1.05 * inch, 0.7 * inch, 2.45 * inch, 1.05 * inch],
        repeatRows=1,
    )
    records_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                ("SPAN", (0, 1), (-1, 1)) if not records else ("BACKGROUND", (0, 1), (-1, 1), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT_GRAY]),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#dce2ea")),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dce2ea")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend(
        [
            Paragraph("Attendance records", styles["SectionHeading"]),
            records_table,
        ]
    )
    document.build(story, onFirstPage=_add_footer, onLaterPages=_add_footer)
    return output.getvalue()
