# Student Attendance Manager

A browser-based Flask application for student accounts, a private dashboard, and student-specific subject management. Subjects can be registered, edited, and deleted by their owner; scheduled class totals are entered manually.

## Requirements

- Python 3.10 or newer
- Packages listed in `requirements.txt`

## Run locally

From the `StudentAttendanceManager` directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The SQLite database and tables are initialized automatically in `attendance.db`. Existing student accounts are preserved during initialization.

Set a stable secret key in your environment before deployment. For example, generate one with `python -c "import secrets; print(secrets.token_hex(32))"` and set the `SECRET_KEY` environment variable. If not set, the app generates a key for the current process, so active sessions will be invalidated when the app restarts.
