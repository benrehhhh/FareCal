"""Authenticated user routes: dashboard, history, and account settings."""

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database.connection import get_db
from utils.decorators import login_required

user_bp = Blueprint("user", __name__)

HISTORY_PER_PAGE = 20

PASSWORD_MIN_LENGTH = 8


def get_user_history(user_id, limit=None, offset=None):
    """Return a user's calculations, newest first, with transport/passenger names.

    `limit`/`offset` are optional to support pagination and the recent list.
    """
    db = get_db()
    query = """
        SELECT fc.id, fc.distance, fc.regular_fare, fc.discount_percentage,
               fc.discount_amount, fc.final_fare, fc.calculated_at,
               tt.name AS transport_name, pt.name AS passenger_name
        FROM fare_calculations fc
        JOIN transport_types tt ON tt.id = fc.transport_type_id
        JOIN passenger_types pt ON pt.id = fc.passenger_type_id
        WHERE fc.user_id = %s
        ORDER BY fc.calculated_at DESC, fc.id DESC
    """
    params = [user_id]

    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)
        if offset is not None:
            query += " OFFSET %s"
            params.append(offset)

    with db.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def count_user_calculations(user_id):
    """Return the total number of calculations a user has made."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS total FROM fare_calculations WHERE user_id = %s",
            (user_id,),
        )
        return cur.fetchone()["total"]


@user_bp.route("/dashboard")
@login_required
def dashboard():
    """User dashboard: totals, quick actions, recent calculations, quick calculator."""
    user_id = session["user_id"]
    total = count_user_calculations(user_id)
    recent = get_user_history(user_id, limit=5)
    return render_template(
        "dashboard.html",
        total_calculations=total,
        recent=recent,
    )


@user_bp.route("/history")
@login_required
def history():
    """Paginated calculation history."""
    user_id = session["user_id"]
    total = count_user_calculations(user_id)

    per_page = HISTORY_PER_PAGE
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Parse and clamp the page number so out-of-range values never break the page.
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    page = max(1, min(page, total_pages))

    rows = get_user_history(user_id, limit=per_page, offset=(page - 1) * per_page)
    return render_template(
        "history.html",
        rows=rows,
        page=page,
        total_pages=total_pages,
        total=total,
    )


@user_bp.route("/api/history")
def api_history():
    """Return the latest 50 calculations for the logged-in user (JSON)."""
    if not session.get("user_id"):
        return jsonify({"success": False, "message": "Authentication required."}), 401

    rows = get_user_history(session["user_id"], limit=50)
    return jsonify({"success": True, "result": rows})


@user_bp.route("/account")
@login_required
def account_page():
    """Account settings: profile overview, change password, delete account."""
    user_id = session["user_id"]
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, name, email, role, status, created_at FROM users WHERE id = %s",
            (user_id,),
        )
        account = cur.fetchone()

    if account is None:
        # The account no longer exists (deleted from admin) — end the session.
        session.clear()
        return redirect(url_for("index"))

    return render_template("account.html", account=account)


@user_bp.route("/account/change-password", methods=["POST"])
@login_required
def change_password():
    """Verify the current password, then replace it with the new one."""
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT password_hash FROM users WHERE id = %s",
            (session["user_id"],),
        )
        record = cur.fetchone()

    error = None
    if record is None:
        error = "Account not found."
    elif not check_password_hash(record["password_hash"], current):
        error = "Your current password is incorrect."
    elif len(new) < PASSWORD_MIN_LENGTH:
        error = (
            f"The new password must be at least {PASSWORD_MIN_LENGTH} characters long."
        )
    elif new != confirm:
        error = "The new passwords do not match."

    if error:
        flash(error, "warning")
        return redirect(url_for("user.account_page"))

    new_hash = generate_password_hash(new)
    with db.cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (new_hash, session["user_id"]),
        )

    flash("Your password has been updated.", "success")
    return redirect(url_for("user.account_page"))


@user_bp.route("/account/delete", methods=["POST"])
@login_required
def delete_account():
    """Delete the logged-in account; saved history is kept as 'Guest'."""
    user_id = session["user_id"]
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        record = cur.fetchone()

        if record is None:
            session.clear()
            return redirect(url_for("index"))

        # Never let the last active administrator delete the final account.
        if record["role"] == "admin":
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM users
                WHERE id <> %s AND role = 'admin' AND status = 'active'
                """,
                (user_id,),
            )
            if cur.fetchone()["c"] == 0:
                flash(
                    "You cannot delete the only remaining active administrator account.",
                    "warning",
                )
                return redirect(url_for("user.account_page"))

        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))

    session.clear()
    flash("Your account has been deleted. We are sorry to see you go!", "info")
    return redirect(url_for("index"))