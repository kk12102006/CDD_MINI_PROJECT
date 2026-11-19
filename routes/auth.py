import re
import sqlite3
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db_connection import get_db_connection


auth_bp = Blueprint("auth", __name__)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "student_id" not in session:
            flash("Please log in to view your dashboard.", "warning")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped_view


@auth_bp.route("/")
def index():
    return render_template("index.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    usn = request.form.get("usn", "").strip().upper()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not all((name, usn, email, password, confirm_password)):
        flash("Please complete every field.", "danger")
    elif len(name) > 100 or len(usn) > 50:
        flash("Name must be at most 100 characters and USN at most 50 characters.", "danger")
    elif not EMAIL_PATTERN.fullmatch(email):
        flash("Enter a valid email address.", "danger")
    elif len(password) < 8:
        flash("Your password must be at least 8 characters long.", "danger")
    elif password != confirm_password:
        flash("The passwords do not match.", "danger")
    else:
        try:
            with get_db_connection() as connection:
                existing = connection.execute(
                    "SELECT usn, email FROM students WHERE usn = ? OR email = ?",
                    (usn, email),
                ).fetchone()
                if existing:
                    if existing["usn"].casefold() == usn.casefold():
                        flash("That USN is already registered.", "danger")
                    else:
                        flash("That email address is already registered.", "danger")
                else:
                    connection.execute(
                        """
                        INSERT INTO students (name, usn, email, password_hash)
                        VALUES (?, ?, ?, ?)
                        """,
                        (name, usn, email, generate_password_hash(password)),
                    )
                    flash("Your account is ready. You can now log in.", "success")
                    return redirect(url_for("auth.login"))
        except sqlite3.IntegrityError:
            flash("That USN or email address is already registered.", "danger")

    return render_template(
        "register.html",
        form_data={"name": name, "usn": usn, "email": email},
    )


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    identifier = request.form.get("identifier", "").strip()
    password = request.form.get("password", "")
    if not identifier or not password:
        flash("Enter your USN or email address and password.", "danger")
        return render_template("login.html", identifier=identifier)

    with get_db_connection() as connection:
        student = connection.execute(
            """
            SELECT student_id, password_hash
            FROM students
            WHERE usn = ? COLLATE NOCASE OR email = ? COLLATE NOCASE
            """,
            (identifier, identifier),
        ).fetchone()

    if student is None or not check_password_hash(student["password_hash"], password):
        flash("The login details you entered are incorrect.", "danger")
        return render_template("login.html", identifier=identifier)

    session.clear()
    session["student_id"] = student["student_id"]
    return redirect(url_for("dashboard.dashboard"))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.index"))