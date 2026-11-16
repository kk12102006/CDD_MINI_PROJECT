from calendar import month_name
from datetime import date
from io import BytesIO

from flask import (
    Blueprint,
    abort,
    render_template,
    request,
    send_file,
    session,
)

from routes.auth import login_required
from services.excel_report_service import generate_overall_excel
from services.pdf_report_service import generate_overall_pdf, generate_subject_pdf
from services.report_service import (
    create_attendance_progress_chart,
    create_monthly_attendance_chart,
    create_present_absent_chart,
    create_subject_attendance_chart,
    create_subject_comparison_chart,
    get_attendance_records,
    get_monthly_attendance,
    get_monthly_series,
    get_overall_summary,
    get_report_overview,
    get_subject_progress_series,
    parse_report_filters,
)


reports_bp = Blueprint("reports", __name__)


def _report_overview():
    overview = get_report_overview(session["student_id"])
    if overview["student"] is None:
        abort(404)
    return overview


def _subject_summary(subject_id, overview):
    return next(
        (subject for subject in overview["subjects"] if subject["subject_id"] == subject_id),
        None,
    )


def _report_filename_extension(extension):
    return f"attendance_report.{extension}"


@reports_bp.route("/reports")
@login_required
def reports_index():
    overview = _report_overview()
    student_id = session["student_id"]
    year = date.today().year
    monthly_series = get_monthly_series(student_id, year)
    charts = {
        "subject_attendance": create_subject_attendance_chart(
            overview["subjects"]
        ),
        "subject_comparison": create_subject_comparison_chart(
            overview["subjects"]
        ),
        "present_absent": create_present_absent_chart(
            overview["summary"]["present_classes"],
            overview["summary"]["absent_classes"],
        ),
        "monthly": create_monthly_attendance_chart(monthly_series, year),
    }
    return render_template(
        "reports.html",
        student=overview["student"],
        subjects=overview["subjects"],
        summary=overview["summary"],
        charts=charts,
        year=year,
    )


@reports_bp.route("/reports/date-wise")
@login_required
def datewise_report():
    student_id = session["student_id"]
    filters, error = parse_report_filters(request.args, student_id)
    if error:
        abort(400, description=error)

    overview = _report_overview()
    records = get_attendance_records(student_id, filters)
    return render_template(
        "datewise_report.html",
        subjects=overview["subjects"],
        records=records,
        filters=filters,
        record_count=len(records),
        today=date.today().isoformat(),
        current_year=date.today().year,
        month_names=list(month_name)[1:],
    )


@reports_bp.route("/reports/monthly")
@login_required
def monthly_report():
    student_id = session["student_id"]
    filters, error = parse_report_filters(request.args, student_id)
    if error:
        abort(400, description=error)

    year = filters["year"] or date.today().year
    month = filters["month"] or date.today().month
    subject_id = filters["subject_id"]
    overview = _report_overview()
    subjects = overview["subjects"]
    report = get_monthly_attendance(student_id, year, month, subject_id)
    series = get_monthly_series(student_id, year, subject_id)
    chart = create_monthly_attendance_chart(
        series,
        year,
        title=(
            "Monthly attendance"
            if subject_id is None
            else next(
                subject["subject_name"]
                for subject in subjects
                if subject["subject_id"] == subject_id
            )
        ),
    )
    return render_template(
        "monthly_report.html",
        subjects=subjects,
        report=report,
        series=series,
        chart=chart,
        selected_year=year,
        selected_month=month,
        year_options=list(
            range(date.today().year, max(1899, date.today().year - 10), -1)
        ),
        month_names=list(month_name)[1:],
    )


@reports_bp.route("/reports/subject/<int:subject_id>")
@login_required
def subject_report(subject_id):
    overview = _report_overview()
    subject = _subject_summary(subject_id, overview)
    if subject is None:
        abort(404)

    student_id = session["student_id"]
    records = get_attendance_records(
        student_id,
        {"subject_id": subject_id},
    )
    progress = get_subject_progress_series(student_id, subject_id)
    chart = create_attendance_progress_chart(
        progress,
        subject["subject_name"],
        subject["minimum_percentage"],
    )
    monthly_series = get_monthly_series(
        student_id,
        date.today().year,
        subject_id,
    )
    monthly_chart = create_monthly_attendance_chart(
        monthly_series,
        date.today().year,
        title=subject["subject_name"],
    )
    present_absent_chart = create_present_absent_chart(
        subject["present_classes"],
        subject["absent_classes"],
    )
    return render_template(
        "subject_report.html",
        subject=subject,
        records=records,
        progress_chart=chart,
        monthly_chart=monthly_chart,
        present_absent_chart=present_absent_chart,
        year=date.today().year,
    )


@reports_bp.route("/reports/download/pdf")
@login_required
def download_pdf_report():
    overview = _report_overview()
    chart = create_subject_attendance_chart(overview["subjects"])
    pdf_data = generate_overall_pdf(
        overview["student"],
        overview["summary"],
        overview["subjects"],
        {"subject_attendance": chart},
    )
    return send_file(
        BytesIO(pdf_data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=_report_filename_extension("pdf"),
    )


@reports_bp.route("/reports/download/excel")
@login_required
def download_excel_report():
    overview = _report_overview()
    records = get_attendance_records(session["student_id"])
    excel_data = generate_overall_excel(
        overview["student"],
        overview["summary"],
        overview["subjects"],
        records,
    )
    return send_file(
        BytesIO(excel_data),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=_report_filename_extension("xlsx"),
    )


@reports_bp.route("/reports/subject/<int:subject_id>/download/pdf")
@login_required
def download_subject_pdf_report(subject_id):
    overview = _report_overview()
    subject = _subject_summary(subject_id, overview)
    if subject is None:
        abort(404)
    student_id = session["student_id"]
    records = get_attendance_records(
        student_id,
        {"subject_id": subject_id},
    )
    progress = get_subject_progress_series(student_id, subject_id)
    chart = create_attendance_progress_chart(
        progress,
        subject["subject_name"],
        subject["minimum_percentage"],
    )
    pdf_data = generate_subject_pdf(
        overview["student"],
        subject,
        records,
        chart,
    )
    return send_file(
        BytesIO(pdf_data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="subject_attendance_report.pdf",
    )


@reports_bp.route("/reports/subject/<int:subject_id>/download/excel")
@login_required
def download_subject_excel_report(subject_id):
    overview = _report_overview()
    subject = _subject_summary(subject_id, overview)
    if subject is None:
        abort(404)
    student_id = session["student_id"]
    excel_data = generate_overall_excel(
        overview["student"],
        get_overall_summary([subject]),
        [subject],
        get_attendance_records(student_id, {"subject_id": subject_id}),
    )
    return send_file(
        BytesIO(excel_data),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="subject_attendance_report.xlsx",
    )
