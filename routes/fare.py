"""Public fare-related API routes.

Every response uses the same envelope:
    {"success": true,  "result": ... }
    {"success": false, "message": "..." }
"""

from flask import Blueprint, current_app, jsonify, request

from database.connection import get_db
from services.fare_calculator import (
    FareCalculationError,
    calculate_fare,
    _get_current_fare_rate,
    compute_fare,
)

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


@fare_bp.route("/api/transport-types/<int:transport_id>/rate")
def api_transport_rate(transport_id):
    """Return the current active fare rate for one transportation type.

    Drives the Dynamic Rate Panel: fare structure, rounding rule, effective
    date, and the official source reference for the selected transport.
    """
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, name, description FROM transport_types WHERE id = %s AND status = 'active'",
            (transport_id,),
        )
        transport = cur.fetchone()
        if transport is None:
            return (
                jsonify({"success": False, "message": "Transportation type not found."}),
                400,
            )

        rate = _get_current_fare_rate(cur, transport_id)
        if rate is None:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "No active fare rate is configured for this transportation type.",
                    }
                ),
                404,
            )

    # DECIMAL fields must become JSON-friendly floats.
    return jsonify(
        {
            "success": True,
            "result": {
                "transport_type_id": transport["id"],
                "transport_name": transport["name"],
                "transport_description": transport.get("description"),
                "fare_method": rate["fare_method"],
                "base_distance": float(rate["base_distance"]) if rate.get("base_distance") is not None else None,
                "base_fare": float(rate["base_fare"]) if rate.get("base_fare") is not None else None,
                "succeeding_rate": float(rate["succeeding_rate"]) if rate.get("succeeding_rate") is not None else None,
                "per_km_rate": float(rate["per_km_rate"]) if rate.get("per_km_rate") is not None else None,
                "minimum_fare": float(rate["minimum_fare"]) if rate.get("minimum_fare") is not None else None,
                "maximum_fare": float(rate["maximum_fare"]) if rate.get("maximum_fare") is not None else None,
                "rounding_rule": rate["rounding_rule"],
                "effective_date": rate["effective_date"].isoformat() if rate["effective_date"] else None,
                "expiration_date": rate["expiration_date"].isoformat() if rate["expiration_date"] else None,
                "source_reference": rate.get("source_reference"),
            },
        }
    )


@fare_bp.route("/api/fare-preview", methods=["POST"])
def api_fare_preview():
    """Live rate preview: compute a breakdown WITHOUT saving history.

    Expects the same shape as /api/calculate-fare. The response has no
    calculation_id, and nothing is written to fare_calculations.
    """
    try:
        payload = request.json if request.is_json else {}
        result = compute_fare(
            transport_type_id=payload.get("transport_type_id"),
            passenger_type_id=payload.get("passenger_type_id"),
            distance=payload.get("distance"),
        )
    except FareCalculationError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception:
        current_app.logger.exception("Unexpected error in /api/fare-preview")
        return jsonify(
            {
                "success": False,
                "message": "An unexpected error occurred while previewing the fare. "
                "Please try again.",
            }
        ), 500

    return jsonify({"success": True, "result": result})


@fare_bp.route("/api/calculate-fare", methods=["POST"])
def api_calculate_fare():
    """Calculate a fare.

    Expects JSON: {"transport_type_id": 1, "passenger_type_id": 2, "distance": 10.5}
    """
    try:
        payload = request.json if request.is_json else {}
        result = calculate_fare(
            transport_type_id=payload.get("transport_type_id"),
            passenger_type_id=payload.get("passenger_type_id"),
            distance=payload.get("distance"),
            origin_name=payload.get("origin_name"),
            destination_name=payload.get("destination_name"),
            origin_latitude=payload.get("origin_latitude"),
            origin_longitude=payload.get("origin_longitude"),
            destination_latitude=payload.get("destination_latitude"),
            destination_longitude=payload.get("destination_longitude"),
            estimated_duration=payload.get("estimated_duration"),
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