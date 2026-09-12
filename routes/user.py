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
from services.fare_calculator import (
    FareCalculationError,
    _require_id,
    calculate_discount,
    calculate_regular_fare,
    validate_distance,
)
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
        SELECT fc.id, fc.transport_type_id, fc.passenger_type_id,
               fc.distance, fc.regular_fare, fc.discount_percentage,
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
    """User dashboard: totals, quick actions, recent calculations, saved trips."""
    user_id = session["user_id"]
    total = count_user_calculations(user_id)
    recent = get_user_history(user_id, limit=5)
    saved = get_saved_trips(user_id, limit=10)
    return render_template(
        "dashboard.html",
        total_calculations=total,
        recent=recent,
        saved_trips=saved,
    )


def get_saved_trips(user_id, limit=None):
    """Return the user's saved trips, newest first, with transport/passenger names."""
    db = get_db()
    query = """
        SELECT st.id, st.transport_type_id, st.passenger_type_id,
               st.distance_km, st.regular_fare, st.discount_amount,
               st.final_fare, st.created_at,
               tt.name AS transport_name, pt.name AS passenger_name
        FROM saved_trips st
        JOIN transport_types tt ON tt.id = st.transport_type_id
        JOIN passenger_types pt ON pt.id = st.passenger_type_id
        WHERE st.user_id = %s
        ORDER BY st.created_at DESC, st.id DESC
    """
    params = [user_id]
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)

    with db.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def _compute_fare_snapshot(transport_type_id, passenger_type_id, distance):
    """Recompute the fare for a saved trip WITHOUT writing any history rows.

    This mirrors the calculation orchestrator but only reads, so saving a
    trip never pollutes the calculation history. Raises FareCalculationError
    for any invalid input.
    """
    distance = validate_distance(distance)
    transport_type_id = _require_id(transport_type_id, "transportation type")
    passenger_type_id = _require_id(passenger_type_id, "passenger type")

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, name FROM transport_types WHERE id = %s AND status = 'active'",
            (transport_type_id,),
        )
        transport = cur.fetchone()
        if transport is None:
            raise FareCalculationError(
                "The selected transportation type is not available."
            )

        cur.execute(
            """
            SELECT id, name, discount_percentage
            FROM passenger_types
            WHERE id = %s AND status = 'active'
            """,
            (passenger_type_id,),
        )
        passenger = cur.fetchone()
        if passenger is None:
            raise FareCalculationError(
                "The selected passenger type is not available."
            )

        cur.execute(
            """
            SELECT *
            FROM fare_rates
            WHERE transport_type_id = %s
              AND status = 'active'
              AND effective_date <= CURDATE()
              AND (expiration_date IS NULL OR expiration_date >= CURDATE())
            ORDER BY effective_date DESC, id DESC
            LIMIT 1
            """,
            (transport_type_id,),
        )
        rate = cur.fetchone()
        if rate is None:
            raise FareCalculationError(
                "No active fare rate is configured for this transportation type."
            )

    breakdown = calculate_regular_fare(rate, distance)
    discount_percentage = float(passenger["discount_percentage"]) or 0.0
    discount_amount, final_fare = calculate_discount(
        breakdown["regular_fare"], discount_percentage
    )

    return {
        "transport_type_id": transport_type_id,
        "passenger_type_id": passenger_type_id,
        "distance_km": distance,
        "regular_fare": breakdown["regular_fare"],
        "discount_percentage": discount_percentage,
        "discount_amount": discount_amount,
        "final_fare": final_fare,
    }


@user_bp.route("/api/saved-trips", methods=["POST"])
def api_save_trip():
    """Save the current trip for the logged-in user (JSON).

    The server recomputes the fare from the database so the stored snapshot
    is always consistent. Saving the same trip twice returns the existing id.
    """
    if not session.get("user_id"):
        return jsonify({"success": False, "message": "Authentication required."}), 401

    db = get_db()
    payload = request.json if request.is_json else {}
    try:
        trip = _compute_fare_snapshot(
            payload.get("transport_type_id"),
            payload.get("passenger_type_id"),
            payload.get("distance"),
        )
    except FareCalculationError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception:
        current_app.logger.exception("Unexpected error in /api/saved-trips")
        return jsonify(
            {"success": False, "message": "An unexpected error occurred. Please try again."}
        ), 500

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM saved_trips
            WHERE user_id = %s AND transport_type_id = %s
              AND passenger_type_id = %s AND distance_km = %s
              AND final_fare = %s
            ORDER BY id ASC
            LIMIT 1
            """,
            (
                session["user_id"],
                trip["transport_type_id"],
                trip["passenger_type_id"],
                trip["distance_km"],
                trip["final_fare"],
            ),
        )
        existing = cur.fetchone()

        if existing is not None:
            return jsonify(
                {
                    "success": True,
                    "saved": True,
                    "already_saved": True,
                    "trip_id": existing["id"],
                }
            )

        cur.execute(
            """
            INSERT INTO saved_trips
                (user_id, transport_type_id, passenger_type_id, distance_km,
                 regular_fare, discount_amount, final_fare)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                session["user_id"],
                trip["transport_type_id"],
                trip["passenger_type_id"],
                trip["distance_km"],
                trip["regular_fare"],
                trip["discount_amount"],
                trip["final_fare"],
            ),
        )
        trip_id = cur.lastrowid

    return jsonify({"success": True, "saved": True, "already_saved": False, "trip_id": trip_id})


@user_bp.route("/saved-trips/<int:trip_id>/delete", methods=["POST"])
@login_required
def delete_saved_trip(trip_id):
    """Remove one of the logged-in user's saved trips."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT id FROM saved_trips WHERE id = %s AND user_id = %s",
            (trip_id, session["user_id"]),
        )
        if cur.fetchone() is None:
            flash("Saved trip not found.", "warning")
        else:
            cur.execute("DELETE FROM saved_trips WHERE id = %s", (trip_id,))
            flash("Saved trip removed.", "success")

    return redirect(url_for("user.dashboard"))


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