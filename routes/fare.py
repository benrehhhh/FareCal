"""Public fare-related API routes.

Every response uses the same envelope:
    {"success": true,  "result": ... }
    {"success": false, "message": "..." }
"""

from flask import Blueprint, current_app, jsonify, render_template, request, session

from database.connection import get_db
from services.fare_calculator import (
    FareCalculationError,
    calculate_discount,
    calculate_fare,
    calculate_regular_fare,
)

fare_bp = Blueprint("fare", __name__)

SAMPLE_DISTANCES = (2, 5, 10, 20)
DISCOUNT_SAMPLE_PERCENT = 20.0


@fare_bp.route("/fares")
def fares():
    """Public page showing the current fare structure per transport type."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT tt.name AS transport_name, tt.description,
                   fr.fare_method, fr.base_distance, fr.base_fare,
                   fr.succeeding_rate, fr.per_km_rate, fr.minimum_fare,
                   fr.maximum_fare, fr.rounding_rule, fr.effective_date,
                   fr.source_reference
            FROM fare_rates fr
            JOIN transport_types tt ON tt.id = fr.transport_type_id
            WHERE fr.status = 'active'
              AND fr.effective_date <= CURDATE()
              AND (fr.expiration_date IS NULL OR fr.expiration_date >= CURDATE())
            ORDER BY tt.name
            """
        )
        rows = cur.fetchall()

    samples = []
    for rate in rows:
        regular = [
            calculate_regular_fare(rate, d)["regular_fare"]
            for d in SAMPLE_DISTANCES
        ]
        discounted = [
            calculate_discount(r, DISCOUNT_SAMPLE_PERCENT)[1] for r in regular
        ]
        samples.append(
            {
                "rate": rate,
                "distances": SAMPLE_DISTANCES,
                "regular": regular,
                "discounted": discounted,
            }
        )

    return render_template("fares.html", samples=samples)


@fare_bp.route("/api/transport-types")
def api_transport_types():
    """Return the list of active transportation types."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, description
            FROM transport_types
            WHERE status = 'active'
            ORDER BY name
            """
        )
        rows = cur.fetchall()
    return jsonify({"success": True, "result": rows})


@fare_bp.route("/api/passenger-types")
def api_passenger_types():
    """Return the list of active passenger types with their discounts."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, discount_percentage
            FROM passenger_types
            WHERE status = 'active'
            ORDER BY id
            """
        )
        rows = cur.fetchall()
    return jsonify({"success": True, "result": rows})


@fare_bp.route("/api/routes")
def api_routes():
    """Return active common-route presets, optionally filtered by transport."""
    transport_id = request.args.get("transport_id")
    db = get_db()

    sql = """
        SELECT id, transport_type_id, origin, destination, distance_km
        FROM routes
        WHERE status = 'active'
    """
    params = []
    if transport_id:
        try:
            transport_id = int(transport_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Invalid transport id."}), 400
        sql += " AND transport_type_id = %s"
        params.append(transport_id)
    sql += " ORDER BY origin, destination"

    with db.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return jsonify({"success": True, "result": rows})


@fare_bp.route("/api/calculate-fare", methods=["POST"])
def api_calculate_fare():
    """Calculate a fare.

    Expects JSON: {"transport_type_id": 1, "passenger_type_id": 2, "distance": 10.5}
    """
    try:
        result = calculate_fare(
            transport_type_id=request.json.get("transport_type_id")
            if request.is_json
            else None,
            passenger_type_id=request.json.get("passenger_type_id")
            if request.is_json
            else None,
            distance=request.json.get("distance") if request.is_json else None,
            user_id=session.get("user_id"),
        )
    except FareCalculationError as exc:
        # Expected business-rule failures (bad input, inactive type, no rate).
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception:
        # Unexpected errors — log the stack locally but keep the client safe.
        current_app.logger.exception("Unexpected error in /api/calculate-fare")
        return jsonify(
            {
                "success": False,
                "message": "An unexpected error occurred while calculating the fare. "
                "Please try again.",
            }
        ), 500

    return jsonify({"success": True, "result": result})