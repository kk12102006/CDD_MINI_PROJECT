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
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The SQLite database and tables are initialized automatically in `attendance.db`. Existing student accounts are preserved during initialization.

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

Run the automated attendance tests with:

```powershell
python -m unittest discover -s tests -v
```

Set a stable secret key in your environment before deployment. For example, generate one with `python -c "import secrets; print(secrets.token_hex(32))"` and set the `SECRET_KEY` environment variable. If not set, the app generates a key for the current process, so active sessions will be invalidated when the app restarts.
