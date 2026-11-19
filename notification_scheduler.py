import threading

from app import app
from services.notification_scheduler import start_scheduler, stop_scheduler


def main():
    scheduler = start_scheduler(app)
    if scheduler is None:
        raise SystemExit("Another notification scheduler is already running.")

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        stop_scheduler(app)


if __name__ == "__main__":
    main()
