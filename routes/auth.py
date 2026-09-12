"""Authentication routes: register, login, logout."""

import re

import pymysql
from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database.connection import get_db
from utils.csrf import validate_csrf_token

auth_bp = Blueprint("auth", __name__)

PASSWORD_MIN_LENGTH = 8

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Create a new 'user' account."""
    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "POST":
        if not validate_csrf_token():
            abort(400)

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        # --- Server-side validation ------------------------------------
        error = None
        if len(name) < 2:
            error = "Please enter your full name."
        elif not EMAIL_PATTERN.match(email):
            error = "Please enter a valid email address."
        elif len(password) < PASSWORD_MIN_LENGTH:
            error = f"Password must be at least {PASSWORD_MIN_LENGTH} characters long."
        elif password != confirm:
            error = "The passwords do not match."

        if error is None:
            password_hash = generate_password_hash(password)
            db = get_db()
            with db.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO users (name, email, password_hash, role)
                        VALUES (%s, %s, %s, 'user')
                        """,
                        (name, email, password_hash),
                    )
                    db.commit()
                except pymysql.err.IntegrityError:
                    # Duplicate email -> the unique key rejected the insert.
                    error = "That email address is already registered."

        if error:
            return render_template(
                "register.html", error=error, form=request.form
            )

        flash("Your account was created. You may now log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Authenticate a user and start their session."""
    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "POST":
        if not validate_csrf_token():
            abort(400)

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, email, password_hash, role, status
                FROM users
                WHERE email = %s
                """,
                (email,),
            )
            user = cur.fetchone()

        # A generic message on purpose — we do not reveal which part failed.
        if user is None or not check_password_hash(user["password_hash"], password):
            return render_template(
                "login.html", error="Invalid email or password."
            )

        if user["status"] != "active":
            return render_template(
                "login.html", error="This account is inactive. Please contact the administrator."
            )

        # Start the session.
        session.clear()
        session["user_id"] = user["id"]
        session["name"] = user["name"]
        session["email"] = user["email"]
        session["role"] = user["role"]

        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(url_for("index"))

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """End the current session."""
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))