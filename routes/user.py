"""Authenticated user routes: dashboard, history, and account settings."""

import csv
import io

from flask import (
    Blueprint,
    Response,
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


def get_user_history(user_id, limit=None, offset=None, q=None):
    """Return a user's calculations, newest first, with transport/passenger names.

    `limit`/`offset` are optional to support pagination and the recent list.
    `q` filters by transport name or passenger type name (substring match).
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
    """
    params = [user_id]

    if q:
        query += " AND (tt.name LIKE %s OR pt.name LIKE %s)"
        like = f"%{q}%"
        params += [like, like]

    query += " ORDER BY fc.calculated_at DESC, fc.id DESC"

    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)
        if offset is not None:
            query += " OFFSET %s"
            params.append(offset)

    with db.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def count_user_calculations(user_id, q=None):
    """Return how many calculations a user has (optionally filtered by `q`)."""
    db = get_db()
    query = """
        SELECT COUNT(*) AS total
        FROM fare_calculations fc
        JOIN transport_types tt ON tt.id = fc.transport_type_id
        JOIN passenger_types pt ON pt.id = fc.passenger_type_id
        WHERE fc.user_id = %s
    """
    params = [user_id]

    if q:
        query += " AND (tt.name LIKE %s OR pt.name LIKE %s)"
        like = f"%{q}%"
        params += [like, like]

    with db.cursor() as cur:
        cur.execute(query, params)
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
    """Paginated calculation history, searchable by transport/passenger name."""
    user_id = session["user_id"]
    q = request.args.get("q", "").strip()
    total = count_user_calculations(user_id, q=q)

    per_page = HISTORY_PER_PAGE
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Parse and clamp the page number so out-of-range values never break the page.
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    page = max(1, min(page, total_pages))

    rows = get_user_history(user_id, limit=per_page, offset=(page - 1) * per_page, q=q)
    return render_template(
        "history.html",
        rows=rows,
        page=page,
        total_pages=total_pages,
        total=total,
        q=q,
    )


@user_bp.route("/history/export")
@login_required
def export_history():
    """Download the user's calculations as a CSV file (honors the `q` filter)."""
    q = request.args.get("q", "").strip()
    rows = get_user_history(session["user_id"], q=q)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Date",
            "Transport",
            "Distance (km)",
            "Passenger Type",
            "Regular Fare (PHP)",
            "Discount (%)",
            "Discount (PHP)",
            "Final Fare (PHP)",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r["calculated_at"].strftime("%Y-%m-%d %H:%M:%S"),
                r["transport_name"],
                f'{float(r["distance"]):.2f}',
                r["passenger_name"],
                f'{float(r["regular_fare"]):.2f}',
                f'{float(r["discount_percentage"]):.2f}',
                f'{float(r["discount_amount"]):.2f}',
                f'{float(r["final_fare"]):.2f}',
            ]
        )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=farecal_history.csv"},
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