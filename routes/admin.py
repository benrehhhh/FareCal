"""Administrator routes.

Every route here is protected with @admin_required (login required + role
must be 'admin'). Regular users who type an admin URL get a friendly 403 page.
"""

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from database.connection import get_db
from utils.decorators import admin_required

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin")
@admin_required
def dashboard():
    """Admin overview: key counts, most-used transport, recent calculations."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM users")
        total_users = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM transport_types WHERE status = 'active'")
        active_transports = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM fare_rates WHERE status = 'active'")
        active_fare_rates = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM fare_calculations")
        total_calculations = cur.fetchone()["c"]

        cur.execute(
            """
            SELECT tt.name AS transport_name, COUNT(*) AS c
            FROM fare_calculations fc
            JOIN transport_types tt ON tt.id = fc.transport_type_id
            GROUP BY tt.id, tt.name
            ORDER BY c DESC
            LIMIT 1
            """
        )
        most_used = cur.fetchone()

        cur.execute(
            """
            SELECT fc.id, fc.distance, fc.final_fare, fc.calculated_at,
                   tt.name AS transport_name, pt.name AS passenger_name,
                   COALESCE(u.name, 'Guest') AS user_name
            FROM fare_calculations fc
            JOIN transport_types tt ON tt.id = fc.transport_type_id
            JOIN passenger_types pt ON pt.id = fc.passenger_type_id
            LEFT JOIN users u ON u.id = fc.user_id
            ORDER BY fc.calculated_at DESC, fc.id DESC
            LIMIT 5
            """
        )
        recent = cur.fetchall()

    return render_template(
        "admin/dashboard.html",
        active="dashboard",
        total_users=total_users,
        active_transports=active_transports,
        active_fare_rates=active_fare_rates,
        total_calculations=total_calculations,
        most_used=most_used,
        recent=recent,
    )


@admin_bp.route("/admin/users")
@admin_required
def users():
    """List all users, optionally filtered by name or email."""
    q = request.args.get("q", "").strip()
    db = get_db()
    with db.cursor() as cur:
        if q:
            like = f"%{q}%"
            cur.execute(
                """
                SELECT id, name, email, role, status, created_at
                FROM users
                WHERE name LIKE %s OR email LIKE %s
                ORDER BY created_at DESC, id DESC
                """,
                (like, like),
            )
        else:
            cur.execute(
                """
                SELECT id, name, email, role, status, created_at
                FROM users
                ORDER BY created_at DESC, id DESC
                """
            )
        rows = cur.fetchall()
    return render_template("admin/users.html", active="users", users=rows, q=q)


@admin_bp.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id):
    """Activate or deactivate a user account (except your own)."""
    if user_id == session["user_id"]:
        flash("You cannot deactivate your own account.", "warning")
        return redirect(url_for("admin.users"))

    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT status FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()

        if row is None:
            flash("User not found.", "warning")
            return redirect(url_for("admin.users"))

        new_status = "inactive" if row["status"] == "active" else "active"
        cur.execute(
            "UPDATE users SET status = %s WHERE id = %s",
            (new_status, user_id),
        )

    flash(f"User status updated to '{new_status}'.", "success")
    return redirect(url_for("admin.users"))