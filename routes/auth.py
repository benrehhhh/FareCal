"""Authentication routes: register, login, logout."""

import re
from datetime import datetime

import pymysql
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database.connection import get_db
from utils.audit import log_audit
from utils.csrf import validate_csrf_token

auth_bp = Blueprint("auth", __name__)

PASSWORD_MIN_LENGTH = 8

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _record_login_attempt(email, ip_address, success):
    """Log one login attempt; a success also clears prior failures."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO login_attempts (email, ip_address, success)
            VALUES (%s, %s, %s)
            """,
            (email[:150], ip_address, 1 if success else 0),
        )
        if success:
            cur.execute(
                """
                DELETE FROM login_attempts
                WHERE email = %s AND ip_address = %s AND success = 0
                """,
                (email, ip_address),
            )


def _lockout_remaining(email, ip_address):
    """Seconds left in the lockout, or 0 when the user may try again."""
    max_attempts = current_app.config.get("MAX_LOGIN_ATTEMPTS", 5)
    window = int(current_app.config.get("LOGIN_LOCKOUT_SECONDS", 900))

    if not email:
        return 0

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS attempt_count, MIN(attempted_at) AS oldest
            FROM login_attempts
            WHERE email = %s AND ip_address = %s AND success = 0
              AND attempted_at > (NOW() - INTERVAL %s SECOND)
            """,
            (email, ip_address, window),
        )
        row = cur.fetchone()

    if not row or row["attempt_count"] < max_attempts or row["oldest"] is None:
        return 0

    # Locked out until the oldest failure ages out of the window.
    remaining = window - (datetime.now() - row["oldest"]).total_seconds()
    return max(1, int(remaining))


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

        log_audit(None, "user.register", target_type="user", details=email)
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
        ip_address = request.remote_addr or ""

        db = get_db()

        # Throttling: reject before verifying anything once locked.
        lockout_left = _lockout_remaining(email, ip_address)
        if lockout_left:
            minutes = max(1, (lockout_left + 59) // 60)
            return render_template(
                "login.html",
                error=(
                    "Too many failed login attempts. "
                    f"Please try again in about {minutes} minute(s)."
                ),
            )

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
            _record_login_attempt(email, ip_address, success=False)
            return render_template(
                "login.html", error="Invalid email or password."
            )

        if user["status"] != "active":
            _record_login_attempt(email, ip_address, success=False)
            return render_template(
                "login.html", error="This account is inactive. Please contact the administrator."
            )

        _record_login_attempt(email, ip_address, success=True)
        log_audit(
            user["id"],
            "user.login",
            target_type="user",
            target_id=str(user["id"]),
            details=user["email"],
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
    user_id = session.get("user_id")
    email = session.get("email")
    if user_id:
        log_audit(user_id, "user.logout", target_type="user", details=email)
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))