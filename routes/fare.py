"""Public fare-related API routes.

Every response uses the same envelope:
    {"success": true,  "result": ... }
    {"success": false, "message": "..." }
"""

from flask import Blueprint, current_app, jsonify, request, session

from database.connection import get_db
from services.fare_calculator import FareCalculationError, calculate_fare

fare_bp = Blueprint("fare", __name__)


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