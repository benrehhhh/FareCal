"""Administrator routes.

Every route here is protected with @admin_required (login required + role
must be 'admin'). Regular users who type an admin URL get a friendly 403 page.
"""

from datetime import date, datetime

import pymysql
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

CALCULATIONS_PER_PAGE = 20

VALID_FARE_METHODS = ("base_succeeding", "per_km")

VALID_ROUNDING_RULES = ("round_up_025", "round_up_1", "round_2")


def _parse_decimal(value, field_label):
    """Convert form text to a float, or raise ValueError with a friendly message."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"{field_label} must be a valid number.")


def _parse_date(value, field_label):
    """Convert form text to a date, or raise ValueError with a friendly message."""
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{field_label} is required.")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"{field_label} must be a valid date (YYYY-MM-DD).")


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


@admin_bp.route("/admin/transport-types", methods=["GET", "POST"])
@admin_required
def transport_types():
    """List transport types; add a new one via the form above the table."""
    db = get_db()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip() or None

        if len(name) < 2:
            flash("Transport type name must be at least 2 characters.", "warning")
            return redirect(url_for("admin.transport_types"))

        try:
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO transport_types (name, description) VALUES (%s, %s)",
                    (name, description),
                )
            flash(f"Transport type '{name}' added.", "success")
        except pymysql.err.IntegrityError:
            flash("A transport type with that name already exists.", "warning")

        return redirect(url_for("admin.transport_types"))

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, description, status, created_at
            FROM transport_types
            ORDER BY name
            """
        )
        rows = cur.fetchall()
    return render_template(
        "admin/transport_types.html", active="transport_types", rows=rows
    )


@admin_bp.route("/admin/transport-types/<int:tt_id>/toggle", methods=["POST"])
@admin_required
def toggle_transport_type(tt_id):
    """Activate or deactivate a transport type."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT name, status FROM transport_types WHERE id = %s", (tt_id,)
        )
        row = cur.fetchone()

        if row is None:
            flash("Transport type not found.", "warning")
            return redirect(url_for("admin.transport_types"))

        new_status = "inactive" if row["status"] == "active" else "active"
        cur.execute(
            "UPDATE transport_types SET status = %s WHERE id = %s",
            (new_status, tt_id),
        )

    flash(f"Transport type '{row['name']}' is now {new_status}.", "success")
    return redirect(url_for("admin.transport_types"))


@admin_bp.route("/admin/fare-rates", methods=["GET", "POST"])
@admin_required
def fare_rates():
    """List fare rates; add a new one via the form above the table."""
    db = get_db()

    with db.cursor() as cur:
        cur.execute(
            "SELECT id, name FROM transport_types WHERE status = 'active' ORDER BY name"
        )
        transports = cur.fetchall()

    if request.method == "POST":
        transport_id = request.form.get("transport_type_id", "").strip()
        fare_method = request.form.get("fare_method", "")
        submission = {
            "transport_type_id": transport_id,
            "fare_method": fare_method,
            "effective_date": request.form.get("effective_date", "").strip(),
            "status": request.form.get("status", "active"),
            "source_reference": request.form.get("source_reference", "").strip(),
        }

        error = None
        # Numeric fields (all optional except that each method needs its own pair).
        try:
            base_distance = _parse_decimal(request.form.get("base_distance"), "Base distance")
            base_fare = _parse_decimal(request.form.get("base_fare"), "Base fare")
            succeeding_rate = _parse_decimal(request.form.get("succeeding_rate"), "Succeeding rate")
            per_km_rate = _parse_decimal(request.form.get("per_km_rate"), "Per-km rate")
            minimum_fare = _parse_decimal(request.form.get("minimum_fare"), "Minimum fare")
            maximum_fare = _parse_decimal(request.form.get("maximum_fare"), "Maximum fare")
            effective = _parse_date(request.form.get("effective_date"), "Effective date")
            expiration = None
            exp_raw = (request.form.get("expiration_date") or "").strip()
            if exp_raw:
                expiration = _parse_date(exp_raw, "Expiration date")
        except ValueError as exc:
            error = str(exc)

        if error is None:
            if fare_method not in VALID_FARE_METHODS:
                error = "Please choose a valid fare method."
            elif fare_method == "base_succeeding" and (
                base_fare is None or base_distance is None or succeeding_rate is None
            ):
                error = "Base fare, base distance, and succeeding rate are required for this method."
            elif fare_method == "per_km" and per_km_rate is None:
                error = "The per-km rate is required for this method."

        if error is None:
            try:
                with db.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id FROM transport_types WHERE id = %s
                        """,
                        (transport_id,),
                    )
                    if cur.fetchone() is None:
                        error = "Please choose a valid transport type."
            except (ValueError, TypeError):
                error = "Please choose a valid transport type."

        if error is None:
            try:
                with db.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO fare_rates
                            (transport_type_id, fare_method, base_distance, base_fare,
                             succeeding_rate, per_km_rate, minimum_fare, maximum_fare,
                             rounding_rule, effective_date, expiration_date, status,
                             source_reference)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            transport_id,
                            fare_method,
                            base_distance,
                            base_fare,
                            succeeding_rate,
                            per_km_rate,
                            minimum_fare,
                            maximum_fare,
                            request.form.get("rounding_rule", "round_up_025"),
                            effective,
                            expiration,
                            submission["status"],
                            submission["source_reference"],
                        ),
                    )
                flash("Fare rate added.", "success")
            except pymysql.err.IntegrityError:
                flash(
                    "A fare rate for that transport type with the same effective date already exists.",
                    "warning",
                )
            return redirect(url_for("admin.fare_rates"))

        flash(error, "warning")

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT fr.*, tt.name AS transport_name
            FROM fare_rates fr
            JOIN transport_types tt ON tt.id = fr.transport_type_id
            ORDER BY fr.effective_date DESC, tt.name
            """
        )
        rows = cur.fetchall()

    return render_template(
        "admin/fare_rates.html",
        active="fare_rates",
        rows=rows,
        transports=transports,
        today=date.today(),
    )


@admin_bp.route("/admin/fare-rates/<int:fr_id>/toggle", methods=["POST"])
@admin_required
def toggle_fare_rate(fr_id):
    """Activate or deactivate a fare rate."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, status FROM fare_rates WHERE id = %s", (fr_id,)
        )
        row = cur.fetchone()

        if row is None:
            flash("Fare rate not found.", "warning")
            return redirect(url_for("admin.fare_rates"))

        new_status = "inactive" if row["status"] == "active" else "active"
        cur.execute(
            "UPDATE fare_rates SET status = %s WHERE id = %s",
            (new_status, fr_id),
        )

    flash(f"Fare rate is now {new_status}.", "success")
    return redirect(url_for("admin.fare_rates"))


@admin_bp.route("/admin/passenger-types", methods=["GET", "POST"])
@admin_required
def passenger_types():
    """List passenger types; add a new one via the form above the table."""
    db = get_db()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip() or None
        submission = {"name": name, "description": description}

        error = None
        if len(name) < 2:
            error = "Passenger type name must be at least 2 characters."
        else:
            try:
                discount = _parse_decimal(
                    request.form.get("discount_percentage"),
                    "Discount percentage",
                )
                if discount is None:
                    discount = 0.00
                if not 0 <= discount <= 100:
                    error = "Discount percentage must be between 0 and 100."
            except ValueError as exc:
                error = str(exc)

        if error is None:
            try:
                with db.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO passenger_types (name, discount_percentage, description)
                        VALUES (%s, %s, %s)
                        """,
                        (name, discount, description),
                    )
                flash(f"Passenger type '{name}' added.", "success")
            except pymysql.err.IntegrityError:
                flash("A passenger type with that name already exists.", "warning")
            return redirect(url_for("admin.passenger_types"))

        flash(error, "warning")

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, discount_percentage, description, status, created_at
            FROM passenger_types
            ORDER BY name
            """
        )
        rows = cur.fetchall()
    return render_template(
        "admin/passenger_types.html", active="passenger_types", rows=rows
    )


@admin_bp.route("/admin/passenger-types/<int:pt_id>/toggle", methods=["POST"])
@admin_required
def toggle_passenger_type(pt_id):
    """Activate or deactivate a passenger type."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT name, status FROM passenger_types WHERE id = %s", (pt_id,)
        )
        row = cur.fetchone()

        if row is None:
            flash("Passenger type not found.", "warning")
            return redirect(url_for("admin.passenger_types"))

        new_status = "inactive" if row["status"] == "active" else "active"
        cur.execute(
            "UPDATE passenger_types SET status = %s WHERE id = %s",
            (new_status, pt_id),
        )

    flash(f"Passenger type '{row['name']}' is now {new_status}.", "success")
    return redirect(url_for("admin.passenger_types"))


@admin_bp.route("/admin/calculations")
@admin_required
def calculations():
    """Paginated view of every saved calculation (rows can be deleted)."""
    db = get_db()
    q = request.args.get("q", "").strip()

    filter_sql = ""
    params = []
    if q:
        like = f"%{q}%"
        filter_sql = (
            " WHERE (tt.name LIKE %s OR pt.name LIKE %s"
            " OR COALESCE(u.name, 'Guest') LIKE %s)"
        )
        params = [like, like, like]

    base_from = """
        FROM fare_calculations fc
        JOIN transport_types tt ON tt.id = fc.transport_type_id
        JOIN passenger_types pt ON pt.id = fc.passenger_type_id
        LEFT JOIN users u ON u.id = fc.user_id
    """

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total {base_from}{filter_sql}", params)
        total = cur.fetchone()["total"]

    total_pages = max(1, (total + CALCULATIONS_PER_PAGE - 1) // CALCULATIONS_PER_PAGE)

    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    page = max(1, min(page, total_pages))

    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT fc.id, fc.distance, fc.regular_fare, fc.discount_percentage,
                   fc.discount_amount, fc.final_fare, fc.calculated_at,
                   tt.name AS transport_name, pt.name AS passenger_name,
                   COALESCE(u.name, 'Guest') AS user_name
            {base_from}
            {filter_sql}
            ORDER BY fc.calculated_at DESC, fc.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [CALCULATIONS_PER_PAGE, (page - 1) * CALCULATIONS_PER_PAGE],
        )
        rows = cur.fetchall()

    return render_template(
        "admin/calculations.html",
        active="calculations",
        rows=rows,
        page=page,
        total_pages=total_pages,
        total=total,
        q=q,
    )


# ---------------------------------------------------------------------------
# Deletes
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    """Permanently delete an account; the user's history becomes 'Guest'."""
    if user_id == session["user_id"]:
        flash("You cannot delete your own account.", "warning")
        return redirect(url_for("admin.users"))

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT name, role FROM users WHERE id = %s", (user_id,)
        )
        row = cur.fetchone()
        if row is None:
            flash("User not found.", "warning")
            return redirect(url_for("admin.users"))

        cur.execute(
            """
            SELECT COUNT(*) AS c FROM users
            WHERE id <> %s AND role = 'admin' AND status = 'active'
            """,
            (user_id,),
        )
        other_admins = cur.fetchone()["c"]
        if row["role"] == "admin" and other_admins == 0:
            flash(
                "You cannot delete the only remaining active administrator.",
                "warning",
            )
            return redirect(url_for("admin.users"))

        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))

    flash(f"User account '{row['name']}' deleted.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/admin/transport-types/<int:tt_id>/delete", methods=["POST"])
@admin_required
def delete_transport_type(tt_id):
    """Delete a transport type that has no saved calculations using it."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT name FROM transport_types WHERE id = %s", (tt_id,)
        )
        row = cur.fetchone()
        if row is None:
            flash("Transport type not found.", "warning")
            return redirect(url_for("admin.transport_types"))

        cur.execute(
            "SELECT COUNT(*) AS c FROM fare_calculations WHERE transport_type_id = %s",
            (tt_id,),
        )
        used = cur.fetchone()["c"]
        if used:
            flash(
                f"Cannot delete '{row['name']}' — it is used by {used} saved "
                "calculation(s). Deactivate it instead.",
                "warning",
            )
            return redirect(url_for("admin.transport_types"))

        cur.execute("DELETE FROM transport_types WHERE id = %s", (tt_id,))

    flash(f"Transport type '{row['name']}' deleted.", "success")
    return redirect(url_for("admin.transport_types"))


@admin_bp.route("/admin/fare-rates/<int:fr_id>/delete", methods=["POST"])
@admin_required
def delete_fare_rate(fr_id):
    """Delete a fare rate (safe — nothing references a fare rate row)."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT id FROM fare_rates WHERE id = %s", (fr_id,))
        if cur.fetchone() is None:
            flash("Fare rate not found.", "warning")
            return redirect(url_for("admin.fare_rates"))
        cur.execute("DELETE FROM fare_rates WHERE id = %s", (fr_id,))

    flash("Fare rate deleted.", "success")
    return redirect(url_for("admin.fare_rates"))


@admin_bp.route("/admin/passenger-types/<int:pt_id>/delete", methods=["POST"])
@admin_required
def delete_passenger_type(pt_id):
    """Delete a passenger type that has no saved calculations using it."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT name FROM passenger_types WHERE id = %s", (pt_id,)
        )
        row = cur.fetchone()
        if row is None:
            flash("Passenger type not found.", "warning")
            return redirect(url_for("admin.passenger_types"))

        cur.execute(
            "SELECT COUNT(*) AS c FROM fare_calculations WHERE passenger_type_id = %s",
            (pt_id,),
        )
        used = cur.fetchone()["c"]
        if used:
            flash(
                f"Cannot delete '{row['name']}' — it is used by {used} saved "
                "calculation(s). Deactivate it instead.",
                "warning",
            )
            return redirect(url_for("admin.passenger_types"))

        cur.execute("DELETE FROM passenger_types WHERE id = %s", (pt_id,))

    flash(f"Passenger type '{row['name']}' deleted.", "success")
    return redirect(url_for("admin.passenger_types"))


@admin_bp.route("/admin/calculations/<int:calc_id>/delete", methods=["POST"])
@admin_required
def delete_calculation(calc_id):
    """Delete a single saved calculation, then return to the same page."""
    db = get_db()

    try:
        page = int(request.form.get("page", "1"))
    except (TypeError, ValueError):
        page = 1
    page = max(1, page)

    with db.cursor() as cur:
        cur.execute("SELECT id FROM fare_calculations WHERE id = %s", (calc_id,))
        if cur.fetchone() is None:
            flash("Calculation not found.", "warning")
            return redirect(url_for("admin.calculations", page=page))
        cur.execute("DELETE FROM fare_calculations WHERE id = %s", (calc_id,))

    flash("Calculation deleted.", "success")
    return redirect(url_for("admin.calculations", page=page))