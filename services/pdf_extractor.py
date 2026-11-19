import os
import re
import subprocess
import tempfile
from datetime import datetime

import fitz
from PIL import Image, ImageOps

DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


class TimetablePdfError(Exception):
    """Raised when a timetable PDF cannot be read or processed."""


class TesseractUnavailableError(TimetablePdfError):
    """Raised when OCR is required but Tesseract is not installed or configured."""


def _clean_text(value):
    if value is None:
        return ""
    cleaned = value.replace("\xa0", " ").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", cleaned).strip()


def _detect_day(line):
    for day in DAY_NAMES:
        if re.search(rf"\b{re.escape(day)}\b", line, re.IGNORECASE):
            return day
    return None


def _format_time(value):
    value = re.sub(r"\s+", " ", value.strip().replace(".", ":")).upper()
    if re.fullmatch(r"\d{1,2}\s*(AM|PM)", value):
        value = re.sub(r"(?<=\d)\s*(AM|PM)$", r":00 \1", value)
    if re.fullmatch(r"\d{1,2}:\d{2}\s*(AM|PM)", value):
        return datetime.strptime(value, "%I:%M %p").strftime("%H:%M")
    if re.fullmatch(r"\d{1,2}:\d{2}", value):
        return datetime.strptime(value, "%H:%M").strftime("%H:%M")
    return ""


def _parse_line(line, last_day, subject_names):
    line = _clean_text(line)
    if not line:
        return None

    day = _detect_day(line)
    entry_day = day or last_day
    if not entry_day:
        return None

    match = re.search(
        r"(?:(?:period|p)\s*(?P<period>\d{1,2})\b\s*)?"
        r"(?:\b(?P<day>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b\s*)?"
        r"(?P<start>\d{1,2}(?::\d{2})?\s*(?:AM|PM)?)\s*(?:-|to|–)\s*"
        r"(?P<end>\d{1,2}(?::\d{2})?\s*(?:AM|PM)?)\s*(?P<subject>.*)",
        line,
        re.IGNORECASE,
    )
    if not match:
        return None

    subject_name = _clean_text(match.group("subject"))
    if not subject_name:
        return None

    subject_name = subject_name.strip(" :-|/\\")
    for registered in subject_names:
        if registered and subject_name.casefold() == registered.casefold():
            subject_name = registered
            break
    if not subject_name:
        return None

    start_raw = match.group("start")
    end_raw = match.group("end")
    start_suffix = re.search(r"\b(AM|PM)\b", start_raw, re.IGNORECASE)
    end_suffix = re.search(r"\b(AM|PM)\b", end_raw, re.IGNORECASE)
    if start_suffix and not end_suffix:
        end_raw = f"{end_raw} {start_suffix.group(0)}"
    elif end_suffix and not start_suffix:
        start_raw = f"{start_raw} {end_suffix.group(0)}"

    try:
        start_time = _format_time(start_raw)
        end_time = _format_time(end_raw)
    except ValueError:
        return None
    if not start_time or not end_time:
        return None

    return {
        "day_of_week": entry_day,
        "subject_name": subject_name,
        "start_time": start_time,
        "end_time": end_time,
        "period_number": int(match.group("period")) if match.group("period") else None,
    }


def _extract_entries(text, last_day, subject_names):
    entries = []
    for line in text.splitlines():
        cleaned = _clean_text(line)
        if not cleaned:
            continue
        day = _detect_day(cleaned)
        if day:
            last_day = day
        entry = _parse_line(cleaned, last_day, subject_names)
        if entry:
            entries.append(entry)
    return entries, last_day


def _ocr_page(page):
    image_path = None
    try:
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(3, 3),
            colorspace=fitz.csRGB,
            alpha=False,
        )
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        image = ImageOps.autocontrast(ImageOps.grayscale(image))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
            image_path = image_file.name
        image.save(image_path, format="PNG")
    except (OSError, RuntimeError, ValueError) as error:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)
        raise TimetablePdfError(
            "Unable to prepare this PDF page for OCR. Try a clearer scan or a "
            "text-based PDF."
        ) from error

    try:
        result = subprocess.run(
            [
                os.environ.get("TESSERACT_CMD", "tesseract"),
                image_path,
                "stdout",
                "-l",
                os.environ.get("TESSERACT_LANG", "eng"),
                "--psm",
                "6",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError as error:
        raise TesseractUnavailableError(
            "Scanned PDFs need Tesseract OCR. Install Tesseract and add it to "
            "PATH, or set the TESSERACT_CMD environment variable."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise TimetablePdfError(
            "Tesseract could not finish reading this PDF page. Try a clearer "
            "scan or a text-based PDF."
        ) from error
    except RuntimeError as error:
        raise TimetablePdfError(
            "Tesseract could not finish reading this PDF page. Try a clearer "
            "scan or a text-based PDF."
        ) from error
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)

    if result.returncode != 0:
        raise TimetablePdfError(
            "Tesseract OCR failed to read this PDF page. Check that the selected "
            "OCR language is installed."
        )
    return result.stdout


def extract_timetable_from_pdf(pdf_path, subject_names):
    if not os.path.exists(pdf_path):
        raise TimetablePdfError("The uploaded timetable PDF could not be found.")

    try:
        document = fitz.open(pdf_path)
    except (fitz.FileDataError, RuntimeError) as error:
        raise TimetablePdfError(
            "The uploaded file is not a readable PDF."
        ) from error

    entries = []
    last_day = None
    try:
        for page in document:
            text = page.get_text("text")
            page_entries, last_day = _extract_entries(
                text, last_day, subject_names
            )
            if page_entries:
                entries.extend(page_entries)
            else:
                ocr_text = _ocr_page(page)
                ocr_entries, last_day = _extract_entries(
                    ocr_text, last_day, subject_names
                )
                entries.extend(ocr_entries)
    except TimetablePdfError:
        raise
    except (RuntimeError, ValueError) as error:
        raise TimetablePdfError(
            "An error occurred while extracting timetable data from this PDF."
        ) from error
    finally:
        document.close()

    return entries
