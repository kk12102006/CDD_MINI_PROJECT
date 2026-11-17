import os

from flask import Flask
from flask_wtf.csrf import CSRFProtect

from config import Config
from database.db_connection import init_db
from routes.auth import auth_bp
from routes.attendance import attendance_bp
from routes.dashboard import dashboard_bp
from routes.reports import reports_bp
from routes.subjects import subjects_bp
from routes.tasks import tasks_bp
from routes.timetable import timetable_bp
from routes.notification_settings import notification_settings_bp


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    CSRFProtect(app)
    init_db(app.config["DATABASE"])
    app.register_blueprint(auth_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(subjects_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(notification_settings_bp)
    app.register_blueprint(timetable_bp)
    return app


app = create_app()


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG") == "1"
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        from services.notification_scheduler import start_scheduler

        start_scheduler(app)
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=debug,
    )