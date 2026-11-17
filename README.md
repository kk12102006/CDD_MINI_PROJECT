# Student Attendance Manager

A browser-based Flask application for student accounts, a private dashboard, subject management, weekly timetable management, and daily attendance. Subjects can be registered, edited, and deleted by their owner; scheduled class totals are entered manually.

## Requirements

- Python 3.10 or newer
- Packages listed in `requirements.txt`
- Tesseract OCR (required only for scanned/image-based timetable PDFs)

## Run locally

From the `StudentAttendanceManager` directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The SQLite database and tables are initialized automatically in `attendance.db`. Existing student accounts are preserved during initialization.

### Email notifications

The app loads `.env` from the project directory. Set `SMTP_EMAIL` to the Gmail account used to send notifications and `SMTP_APP_PASSWORD` to a Google App Password (not the Gmail sign-in password). Google requires 2-Step Verification before an App Password can be created. Keep `.env` private; it is excluded by `.gitignore`. `SMTP_HOST`, `SMTP_PORT`, and `NOTIFICATION_TIMEZONE` default to `smtp.gmail.com`, `587`, and `Asia/Kolkata`.

Signed-in students can enable attendance and task notifications independently from **Notification Preferences** on the dashboard and select separate 24-hour times. Preferences default to disabled to avoid sending email before a student opts in. Notifications go to the email address already on the student's account.

At the configured task-notification time, one email bundles all pending task reminders due within seven days, including tasks due today or overdue. Deadlines from yesterday through tomorrow are labeled **Yesterday**, **Today**, or **Tomorrow**; other deadlines show their date.

`python app.py` starts the web app and its single-instance scheduler for local use. In production, run one persistent scheduler process alongside the web workers with `python notification_scheduler.py`; web workers do not each start their own scheduler. The scheduler checks preferences every minute and uses SQLite uniqueness constraints to prevent repeat sends. Keep the scheduler process running under a service manager (for example, systemd, a Windows service, or a process supervisor). Platforms that suspend background processes need a separate always-on worker or scheduled-job service.

Email failures are recorded in `notification_logs` and are not retried during the same calendar day; the next scheduled day can try again. If the scheduler starts after a student's configured time, that day's unsent notification is picked up on its next check. Without valid SMTP settings, email attempts are logged as failed. Use a test account or controlled test addresses to verify delivery; the automated tests mock SMTP and do not send real email.

### Scanned timetable PDFs

Text-based PDFs are read directly. Scanned/image-based PDFs use Tesseract OCR locally; document images are not sent to an external service. On Windows, install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki), then reopen the terminal so its `tesseract` command is available on `PATH`. If it is installed elsewhere, set its executable path before starting the app:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
python app.py
```

The default OCR language is English; set `TESSERACT_LANG` to a language code installed with Tesseract if needed.

OCR results are estimates. Review and correct every extracted entry on the preview page before saving. Complex timetable layouts, low-resolution scans, and handwriting may not be recognized accurately.

### Daily attendance

Open **Attendance** while signed in to mark each period from your saved weekly timetable. Select a past or current date, choose Present, Absent, or No class for every period, and save. No class is stored separately and does not count toward completed attendance. The manually entered total scheduled classes remains unchanged; Present and Absent records are blocked once that total is reached. Use **Attendance history** to review and correct saved records.

Choose **Attendance overview** from the Attendance menu to view subject-wise present, absent, completed and no-class counts, attendance percentage, and allowed/remaining absences. These values are recalculated from saved attendance records whenever the overview loads. Reaching the absence limit displays an absent-deadline warning; exceeding it displays an attendance-shortage warning as well.

### Reports

Open **Reports** to view overall and subject-wise attendance charts, summaries, and alerts. Monthly and date-wise reports can be filtered by subject and attendance status; date-wise reports also accept a date range. Each report is limited to the signed-in student's records. Download an overall PDF or Excel workbook from the reports page, or download a subject-specific PDF or workbook from that subject's report.

### Tasks and deadline reminders

Open **Tasks** to create and manage academic or personal tasks. Tasks can optionally be linked to one of your subjects; task records are private to the signed-in student. Pending tasks appear in the dashboard's **REMAINING TASKS** section starting seven days before their deadline and remain visible there until completed, including after becoming overdue. The task page separates overdue, pending, and completed tasks. Completing a task records its completion time; reopening it clears that time.

Run the automated test suite with:

```powershell
python -m unittest discover -s tests -v
```

Notification tests can be run separately with:

```powershell
python -m unittest discover -s tests -p "test_notifications.py" -v
```

Set a stable secret key in your environment before deployment. For example, generate one with `python -c "import secrets; print(secrets.token_hex(32))"` and set the `SECRET_KEY` environment variable. If not set, the app generates a key for the current process, so active sessions will be invalidated when the app restarts.
