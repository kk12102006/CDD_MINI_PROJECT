import os
import re

import fitz

DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
TIME_PATTERN = re.compile(
    r"(?P<start>\d{1,2}:\d{2})\s*(?:-|to|–)\s*(?P<end>\d{1,2}:\d{2})",
    re.IGNORECASE,
)


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
    value = value.strip().replace(".", ":")
    if re.fullmatch(r"\d{1,2}:\d{2}", value):
        return value
    return value


def _parse_line(line, last_day, subject_names):
    line = _clean_text(line)
    if not line:
        return None

    day = _detect_day(line)
    entry_day = day or last_day
    if not entry_day:
        return None

    match = re.search(
        r"(?:\b(?P<day>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b\s*)?"
        r"(?P<start>\d{1,2}:\d{2})\s*(?:-|to|–)\s*(?P<end>\d{1,2}:\d{2})\s*(?P<subject>.*)",
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

    start_time = _format_time(match.group("start"))
    end_time = _format_time(match.group("end"))
    if not start_time or not end_time:
        return None

    return {
        "day_of_week": entry_day,
        "subject_name": subject_name,
        "start_time": start_time,
        "end_time": end_time,
        "period_number": None,
    }


def extract_timetable_from_pdf(pdf_path, subject_names):
    if not os.path.exists(pdf_path):
        return []

    try:
        document = fitz.open(pdf_path)
    except Exception:
        return []

    entries = []
    last_day = None
    try:
        for page in document:
            text = page.get_text("text")
            for line in text.splitlines():
                cleaned = _clean_text(line)
                if not cleaned:
                    continue
                if _detect_day(cleaned):
                    last_day = _detect_day(cleaned)
                entry = _parse_line(cleaned, last_day, subject_names)
                if entry:
                    entries.append(entry)
    except Exception:
        return []
    finally:
        document.close()

    return entries
