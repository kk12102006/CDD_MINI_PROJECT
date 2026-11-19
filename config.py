import os
import secrets
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", BASE_DIR))
UPLOAD_DIR = DATA_DIR / "uploads" / "timetables"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    DATABASE = str(DATA_DIR / "attendance.db")
    UPLOAD_FOLDER = str(UPLOAD_DIR)
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    ALLOWED_EXTENSIONS = {".pdf"}
    TESSERACT_CMD = os.environ.get("TESSERACT_CMD")
    TESSERACT_LANG = os.environ.get("TESSERACT_LANG", "eng")
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = os.environ.get("SMTP_PORT", "587")
    SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
    SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")
    NOTIFICATION_TIMEZONE = os.environ.get(
        "NOTIFICATION_TIMEZONE", "Asia/Kolkata"
    )
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"