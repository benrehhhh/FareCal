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
from werkzeug.security import generate_password_hash

from database.connection import get_db
from utils.audit import log_audit
from utils.decorators import admin_required

from config import MAX_DISTANCE_KM
from routes.auth import PASSWORD_MIN_LENGTH

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


def _parse_fare_rate_fields(form):
    """Parse and validate a fare-rate form. Returns (data_dict, error).

    `data_dict` mirrors the fare_rates columns; `error` is None when valid.
    """
    transport_id = form.get("transport_type_id", "").strip()
    fare_method = form.get("fare_method", "")

    error = None
    try:
        base_distance = _parse_decimal(form.get("base_distance"), "Base distance")
        base_fare = _parse_decimal(form.get("base_fare"), "Base fare")
        succeeding_rate = _parse_decimal(
            form.get("succeeding_rate"), "Succeeding rate"
        )
        per_km_rate = _parse_decimal(form.get("per_km_rate"), "Per-km rate")
        minimum_fare = _parse_decimal(form.get("minimum_fare"), "Minimum fare")
        maximum_fare = _parse_decimal(form.get("maximum_fare"), "Maximum fare")
        effective = _parse_date(form.get("effective_date"), "Effective date")
        expiration = None
        exp_raw = (form.get("expiration_date") or "").strip()
        if exp_raw:
            expiration = _parse_date(exp_raw, "Expiration date")
    except ValueError as exc:
        return None, str(exc)

    if fare_method not in VALID_FARE_METHODS:
        error = "Please choose a valid fare method."
    elif fare_method == "base_succeeding" and (
        base_fare is None or base_distance is None or succeeding_rate is None
    ):
        error = "Base fare, base distance, and succeeding rate are required for this method."
    elif fare_method == "per_km" and per_km_rate is None:
        error = "The per-km rate is required for this method."

    data = {
        "transport_type_id": transport_id,
        "fare_method": fare_method,
        "base_distance": base_distance,
        "base_fare": base_fare,
        "succeeding_rate": succeeding_rate,
        "per_km_rate": per_km_rate,
        "minimum_fare": minimum_fare,
        "maximum_fare": maximum_fare,
        "rounding_rule": form.get("rounding_rule", "round_up_025"),
        "effective_date": effective,
        "expiration_date": expiration,
        "status": form.get("status", "active"),
        "source_reference": form.get("source_reference", "").strip(),
    }
    return data, error


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
            "SELECT COUNT(*) AS c FROM users WHERE status = 'active'"
        )
        active_users = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'")
        admin_count = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(*) AS c FROM users WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)"
        )
        new_users_7d = cur.fetchone()["c"]

        cur.execute(
            """
            SELECT COUNT(*) AS c FROM fare_calculations
            WHERE calculated_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            """
        )
        calcs_7d = cur.fetchone()["c"]

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
        active_users=active_users,
        admin_count=admin_count,
        new_users_7d=new_users_7d,
        calcs_7d=calcs_7d,
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
    log_audit(
        session["user_id"],
        "admin.toggle_user",
        target_type="user",
        target_id=str(user_id),
        details=f"status -> {new_status}",
    )
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
            log_audit(
                session["user_id"],
                "admin.add_transport_type",
                target_type="transport_type",
                details=name,
            )
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
    log_audit(
        session["user_id"],
        "admin.toggle_transport_type",
        target_type="transport_type",
        target_id=str(tt_id),
        details=f"{row['name']} -> {new_status}",
    )
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
        data, error = _parse_fare_rate_fields(request.form)

        if error is None:
            try:
                transport_id = int(data["transport_type_id"])
            except (ValueError, TypeError):
                error = "Please choose a valid transport type."
            else:
                with db.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM transport_types WHERE id = %s",
                        (transport_id,),
                    )
                    if cur.fetchone() is None:
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
                            data["fare_method"],
                            data["base_distance"],
                            data["base_fare"],
                            data["succeeding_rate"],
                            data["per_km_rate"],
                            data["minimum_fare"],
                            data["maximum_fare"],
                            data["rounding_rule"],
                            data["effective_date"],
                            data["expiration_date"],
                            data["status"],
                            data["source_reference"],
                        ),
                    )
                flash("Fare rate added.", "success")
                log_audit(
                    session["user_id"],
                    "admin.add_fare_rate",
                    target_type="fare_rate",
                    details=f"transport {transport_id}, effective {data['effective_date']}",
                )
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
    log_audit(
        session["user_id"],
        "admin.toggle_fare_rate",
        target_type="fare_rate",
        target_id=str(fr_id),
        details=f"{new_status}",
    )
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
                log_audit(
                    session["user_id"],
                    "admin.add_passenger_type",
                    target_type="passenger_type",
                    details=name,
                )
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
    log_audit(
        session["user_id"],
        "admin.toggle_passenger_type",
        target_type="passenger_type",
        target_id=str(pt_id),
        details=f"{row['name']} -> {new_status}",
    )
    return redirect(url_for("admin.passenger_types"))


@admin_bp.route("/admin/routes", methods=["GET", "POST"])
@admin_required
def routes():
    """List common-route presets; add a new one via the form above the table."""
    db = get_db()

    with db.cursor() as cur:
        cur.execute(
            "SELECT id, name FROM transport_types WHERE status = 'active' ORDER BY name"
        )
        transports = cur.fetchall()

    if request.method == "POST":
        transport_id = request.form.get("transport_type_id", "").strip()
        origin = request.form.get("origin", "").strip()
        destination = request.form.get("destination", "").strip()

        error = None
        try:
            distance = _parse_decimal(request.form.get("distance_km"), "Distance")
        except ValueError as exc:
            error = str(exc)
            distance = None

        if error is None:
            if len(origin) < 2:
                error = "Origin must be at least 2 characters."
            elif len(destination) < 2:
                error = "Destination must be at least 2 characters."
            elif distance is None or distance <= 0:
                error = "Distance must be greater than zero."
            elif distance > MAX_DISTANCE_KM:
                error = f"Distance cannot exceed {MAX_DISTANCE_KM} km."

        if error is None:
            with db.cursor() as cur:
                cur.execute(
                    "SELECT id FROM transport_types WHERE id = %s", (transport_id,)
                )
                if cur.fetchone() is None:
                    error = "Please choose a valid transport type."
                else:
                    try:
                        cur.execute(
                            """
                            INSERT INTO routes
                                (transport_type_id, origin, destination, distance_km)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (transport_id, origin, destination, distance),
                        )
                    except pymysql.err.IntegrityError:
                        error = (
                            "A route with that transport, origin, and destination "
                            "already exists."
                        )

        if error is None:
            flash(f"Route '{origin} → {destination}' added.", "success")
            log_audit(
                session["user_id"],
                "admin.add_route",
                target_type="route",
                details=f"{origin} -> {destination}",
            )
        else:
            flash(error, "warning")
        return redirect(url_for("admin.routes"))

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.origin, r.destination, r.distance_km, r.status,
                   tt.name AS transport_name
            FROM routes r
            JOIN transport_types tt ON tt.id = r.transport_type_id
            ORDER BY tt.name, r.origin, r.destination
            """
        )
        rows = cur.fetchall()

    return render_template(
        "admin/routes.html",
        active="routes",
        rows=rows,
        transports=transports,
    )


@admin_bp.route("/admin/routes/<int:route_id>/toggle", methods=["POST"])
@admin_required
def toggle_route(route_id):
    """Activate or deactivate a saved route."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT origin, status FROM routes WHERE id = %s", (route_id,))
        row = cur.fetchone()

        if row is None:
            flash("Route not found.", "warning")
            return redirect(url_for("admin.routes"))

        new_status = "inactive" if row["status"] == "active" else "active"
        cur.execute(
            "UPDATE routes SET status = %s WHERE id = %s", (new_status, route_id)
        )

    flash(f"Route is now {new_status}.", "success")
    log_audit(
        session["user_id"],
        "admin.toggle_route",
        target_type="route",
        target_id=str(route_id),
        details=f"{new_status}",
    )
    return redirect(url_for("admin.routes"))


@admin_bp.route("/admin/routes/<int:route_id>/delete", methods=["POST"])
@admin_required
def delete_route(route_id):
    """Delete a saved route preset."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT origin, destination FROM routes WHERE id = %s", (route_id,)
        )
        row = cur.fetchone()
        if row is None:
            flash("Route not found.", "warning")
            return redirect(url_for("admin.routes"))
        cur.execute("DELETE FROM routes WHERE id = %s", (route_id,))

    flash(f"Route '{row['origin']} → {row['destination']}' deleted.", "success")
    log_audit(
        session["user_id"],
        "admin.delete_route",
        target_type="route",
        target_id=str(route_id),
        details=f"{row['origin']} -> {row['destination']}",
    )
    return redirect(url_for("admin.routes"))


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


AUDIT_PER_PAGE = 25


@admin_bp.route("/admin/audit")
@admin_required
def audit():
    """Paginated, searchable view of the audit log."""
    q = request.args.get("q", "").strip()
    db = get_db()

    filter_sql = ""
    params = []
    if q:
        like = f"%{q}%"
        filter_sql = (
            " WHERE (al.action LIKE %s OR al.details LIKE %s"
            " OR al.target_type LIKE %s OR COALESCE(u.email, '-') LIKE %s"
            " OR al.ip_address LIKE %s)"
        )
        params = [like, like, like, like, like]

    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM audit_log al
            LEFT JOIN users u ON u.id = al.user_id
            {filter_sql}
            """,
            params,
        )
        total = cur.fetchone()["total"]

    total_pages = max(1, (total + AUDIT_PER_PAGE - 1) // AUDIT_PER_PAGE)

    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    page = max(1, min(page, total_pages))

    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT al.id, al.action, al.target_type, al.target_id,
                   al.details, al.ip_address, al.created_at,
                   COALESCE(u.email, '-') AS actor_email
            FROM audit_log al
            LEFT JOIN users u ON u.id = al.user_id
            {filter_sql}
            ORDER BY al.created_at DESC, al.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [AUDIT_PER_PAGE, (page - 1) * AUDIT_PER_PAGE],
        )
        rows = cur.fetchall()

    return render_template(
        "admin/audit.html",
        active="audit",
        rows=rows,
        page=page,
        total_pages=total_pages,
        total=total,
        q=q,
    )


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/transport-types/<int:tt_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_transport_type(tt_id):
    """Edit a transport type's name/description."""
    db = get_db()

    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM transport_types WHERE id = %s", (tt_id,)
        )
        row = cur.fetchone()

    if row is None:
        flash("Transport type not found.", "warning")
        return redirect(url_for("admin.transport_types"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip() or None

        if len(name) < 2:
            flash("Transport type name must be at least 2 characters.", "warning")
        else:
            try:
                with db.cursor() as cur:
                    cur.execute(
                        "UPDATE transport_types SET name = %s, description = %s WHERE id = %s",
                        (name, description, tt_id),
                    )
                flash(f"Transport type '{name}' updated.", "success")
                log_audit(
                    session["user_id"],
                    "admin.edit_transport_type",
                    target_type="transport_type",
                    target_id=str(tt_id),
                    details=name,
                )
            except pymysql.err.IntegrityError:
                flash("A transport type with that name already exists.", "warning")

        return redirect(url_for("admin.edit_transport_type", tt_id=tt_id))

    return render_template(
        "admin/edit_transport_type.html", active="transport_types", row=row
    )


@admin_bp.route("/admin/passenger-types/<int:pt_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_passenger_type(pt_id):
    """Edit a passenger type's name, discount, and description."""
    db = get_db()

    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM passenger_types WHERE id = %s", (pt_id,)
        )
        row = cur.fetchone()

    if row is None:
        flash("Passenger type not found.", "warning")
        return redirect(url_for("admin.passenger_types"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip() or None

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
                        UPDATE passenger_types
                        SET name = %s, discount_percentage = %s, description = %s
                        WHERE id = %s
                        """,
                        (name, discount, description, pt_id),
                    )
                flash(f"Passenger type '{name}' updated.", "success")
                log_audit(
                    session["user_id"],
                    "admin.edit_passenger_type",
                    target_type="passenger_type",
                    target_id=str(pt_id),
                    details=name,
                )
            except pymysql.err.IntegrityError:
                flash("A passenger type with that name already exists.", "warning")
        else:
            flash(error, "warning")

        return redirect(url_for("admin.edit_passenger_type", pt_id=pt_id))

    return render_template(
        "admin/edit_passenger_type.html", active="passenger_types", row=row
    )


@admin_bp.route("/admin/fare-rates/<int:fr_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_fare_rate(fr_id):
    """Edit an existing fare rate (all fields)."""
    db = get_db()

    with db.cursor() as cur:
        cur.execute("SELECT * FROM fare_rates WHERE id = %s", (fr_id,))
        row = cur.fetchone()
        cur.execute(
            "SELECT id, name FROM transport_types ORDER BY name"
        )
        transports = cur.fetchall()

    if row is None:
        flash("Fare rate not found.", "warning")
        return redirect(url_for("admin.fare_rates"))

    if request.method == "POST":
        data, error = _parse_fare_rate_fields(request.form)

        if error is None:
            try:
                transport_id = int(data["transport_type_id"])
            except (ValueError, TypeError):
                error = "Please choose a valid transport type."
            else:
                with db.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM transport_types WHERE id = %s",
                        (transport_id,),
                    )
                    if cur.fetchone() is None:
                        error = "Please choose a valid transport type."

        if error is None:
            try:
                with db.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE fare_rates
                        SET transport_type_id = %s, fare_method = %s,
                            base_distance = %s, base_fare = %s,
                            succeeding_rate = %s, per_km_rate = %s,
                            minimum_fare = %s, maximum_fare = %s,
                            rounding_rule = %s, effective_date = %s,
                            expiration_date = %s, status = %s,
                            source_reference = %s
                        WHERE id = %s
                        """,
                        (
                            transport_id,
                            data["fare_method"],
                            data["base_distance"],
                            data["base_fare"],
                            data["succeeding_rate"],
                            data["per_km_rate"],
                            data["minimum_fare"],
                            data["maximum_fare"],
                            data["rounding_rule"],
                            data["effective_date"],
                            data["expiration_date"],
                            data["status"],
                            data["source_reference"],
                            fr_id,
                        ),
                    )
                flash("Fare rate updated.", "success")
                log_audit(
                    session["user_id"],
                    "admin.edit_fare_rate",
                    target_type="fare_rate",
                    target_id=str(fr_id),
                    details=f"transport {transport_id}, effective {data['effective_date']}",
                )
            except pymysql.err.IntegrityError:
                flash(
                    "A fare rate for that transport type with the same effective date already exists.",
                    "warning",
                )
            return redirect(url_for("admin.fare_rates"))

        flash(error, "warning")

    return render_template(
        "admin/edit_fare_rate.html",
        active="fare_rates",
        row=row,
        transports=transports,
        today=date.today(),
        rounding_rules=VALID_ROUNDING_RULES,
    )


@admin_bp.route("/admin/routes/<int:route_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_route(route_id):
    """Edit a saved route preset."""
    db = get_db()

    with db.cursor() as cur:
        cur.execute("SELECT * FROM routes WHERE id = %s", (route_id,))
        row = cur.fetchone()
        cur.execute(
            "SELECT id, name FROM transport_types ORDER BY name"
        )
        transports = cur.fetchall()

    if row is None:
        flash("Route not found.", "warning")
        return redirect(url_for("admin.routes"))

    if request.method == "POST":
        transport_id = request.form.get("transport_type_id", "").strip()
        origin = request.form.get("origin", "").strip()
        destination = request.form.get("destination", "").strip()

        error = None
        try:
            distance = _parse_decimal(
                request.form.get("distance_km"), "Distance"
            )
        except ValueError as exc:
            error = str(exc)
            distance = None

        if error is None:
            if len(origin) < 2:
                error = "Origin must be at least 2 characters."
            elif len(destination) < 2:
                error = "Destination must be at least 2 characters."
            elif distance is None or distance <= 0:
                error = "Distance must be greater than zero."
            elif distance > MAX_DISTANCE_KM:
                error = f"Distance cannot exceed {MAX_DISTANCE_KM} km."

        if error is None:
            try:
                transport_id = int(transport_id)
            except (ValueError, TypeError):
                error = "Please choose a valid transport type."
            else:
                with db.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM transport_types WHERE id = %s",
                        (transport_id,),
                    )
                    if cur.fetchone() is None:
                        error = "Please choose a valid transport type."

        if error is None:
            try:
                with db.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE routes
                        SET transport_type_id = %s, origin = %s,
                            destination = %s, distance_km = %s
                        WHERE id = %s
                        """,
                        (transport_id, origin, destination, distance, route_id),
                    )
                flash(f"Route '{origin} → {destination}' updated.", "success")
                log_audit(
                    session["user_id"],
                    "admin.edit_route",
                    target_type="route",
                    target_id=str(route_id),
                    details=f"{origin} -> {destination}",
                )
            except pymysql.err.IntegrityError:
                flash(
                    "A route with that transport, origin, and destination already exists.",
                    "warning",
                )
            return redirect(url_for("admin.routes"))

        flash(error, "warning")

    return render_template(
        "admin/edit_route.html",
        active="routes",
        row=row,
        transports=transports,
    )


@admin_bp.route("/admin/users/<int:user_id>/reset-password", methods=["GET", "POST"])
@admin_required
def reset_password(user_id):
    """Let an administrator set a new password for a user account."""
    db = get_db()

    with db.cursor() as cur:
        cur.execute(
            "SELECT id, name, email FROM users WHERE id = %s", (user_id,)
        )
        user = cur.fetchone()

    if user is None:
        flash("User not found.", "warning")
        return redirect(url_for("admin.users"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(new_password) < PASSWORD_MIN_LENGTH:
            flash(
                f"Password must be at least {PASSWORD_MIN_LENGTH} characters long.",
                "warning",
            )
        elif new_password != confirm_password:
            flash("The passwords do not match.", "warning")
        else:
            password_hash = generate_password_hash(new_password)
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE users SET password_hash = %s WHERE id = %s",
                    (password_hash, user_id),
                )
            flash(f"Password reset for '{user['name']}'.", "success")
            log_audit(
                session["user_id"],
                "admin.reset_password",
                target_type="user",
                target_id=str(user_id),
                details=user["email"],
            )
            return redirect(url_for("admin.users"))

    return render_template(
        "admin/user_password_reset.html", active="users", user=user
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
    log_audit(
        session["user_id"],
        "admin.delete_user",
        target_type="user",
        target_id=str(user_id),
        details=row["name"],
    )
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
    log_audit(
        session["user_id"],
        "admin.delete_transport_type",
        target_type="transport_type",
        target_id=str(tt_id),
        details=row["name"],
    )
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
    log_audit(
        session["user_id"],
        "admin.delete_fare_rate",
        target_type="fare_rate",
        target_id=str(fr_id),
    )
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
    log_audit(
        session["user_id"],
        "admin.delete_passenger_type",
        target_type="passenger_type",
        target_id=str(pt_id),
        details=row["name"],
    )
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
    log_audit(
        session["user_id"],
        "admin.delete_calculation",
        target_type="calculation",
        target_id=str(calc_id),
    )
    return redirect(url_for("admin.calculations", page=page))