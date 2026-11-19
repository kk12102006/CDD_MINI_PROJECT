import hashlib
import logging
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from filelock import FileLock, Timeout

from services.notification_service import process_due_notifications


logger = logging.getLogger(__name__)
EXTENSION_KEY = "notification_scheduler"


def _run_job(app):
    try:
        with app.app_context():
            process_due_notifications()
    except Exception as error:
        app.logger.error(
            "Notification scheduler run failed (%s).",
            type(error).__name__,
        )


def start_scheduler(app):
    if EXTENSION_KEY in app.extensions:
        return app.extensions[EXTENSION_KEY]["scheduler"]

    database_path = str(Path(app.config["DATABASE"]).resolve())
    lock_name = hashlib.sha256(database_path.encode("utf-8")).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / f"attendly-notifications-{lock_name}.lock"
    lock = FileLock(str(lock_path), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        logger.info("A notification scheduler is already running for this database.")
        return None

    scheduler = BackgroundScheduler(
        timezone=ZoneInfo(app.config["NOTIFICATION_TIMEZONE"])
    )
    scheduler.add_job(
        _run_job,
        trigger=CronTrigger(
            second=0,
            timezone=ZoneInfo(app.config["NOTIFICATION_TIMEZONE"]),
        ),
        args=[app],
        id="dispatch-notifications-every-minute",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=50,
    )
    scheduler.start()
    app.extensions[EXTENSION_KEY] = {"scheduler": scheduler, "lock": lock}
    logger.info("Notification scheduler started.")
    return scheduler


def stop_scheduler(app):
    state = app.extensions.pop(EXTENSION_KEY, None)
    if state is None:
        return
    scheduler = state["scheduler"]
    if scheduler.running:
        scheduler.shutdown(wait=True)
    state["lock"].release()
