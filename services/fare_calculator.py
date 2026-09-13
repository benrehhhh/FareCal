"""Fare calculation engine for FareCal.

The engine is split into two layers:

1. Pure calculation functions (no database access) — easy to unit test.
   These live at the bottom of this file.
2. A database-driven orchestrator (`calculate_fare`) that loads the active
   fare rule and passenger discount from MySQL, runs the pure functions,
   and saves the result to the calculation history.

Supported fare methods (stored in fare_rates.fare_method):

- 'base_succeeding' : pay `base_fare` for the first `base_distance` km,
                       then `succeeding_rate` for every extra km.
- 'per_km'          : pay `per_km_rate` per kilometer (a minimum/maximum
                       fare can also be configured).

Supported rounding rules (stored in fare_rates.rounding_rule):

- 'round_up_025' : round UP to the next PHP 0.25 (jeepney practice)
- 'round_up_1'   : round UP to the next whole peso
- 'round_2'      : standard two-decimal rounding (default fallback)

Fare rates and discounts are NEVER hard-coded in the frontend — everything
comes from the database.
"""

import math

from config import MAX_DISTANCE_KM
from database.connection import get_db


class FareCalculationError(Exception):
    """Raised whenever a fare cannot be computed for business reasons."""


# ---------------------------------------------------------------------------
# Pure calculation functions
# ---------------------------------------------------------------------------

def _maybe_float(value):
    """Convert a database DECIMAL / string / None into float or None."""
    if value is None or value == "":
        return None
    return float(value)


def _round_up_025(value):
    """Round up to the next multiple of PHP 0.25."""
    return math.ceil(value * 4) / 4


def _round_up_1(value):
    """Round up to the next whole peso."""
    return math.ceil(value)


def _round_2(value):
    """Standard two-decimal rounding."""
    return round(value, 2)


#: Maps a stored rounding_rule key to its function.
ROUNDING_RULES = {
    "round_up_025": _round_up_025,
    "round_up_1": _round_up_1,
    "round_2": _round_2,
}


def apply_rounding(value, rule=None):
    """Round `value` according to the rule key. Unknown rules fall back to 2 decimals."""
    rounding_fn = ROUNDING_RULES.get(rule, _round_2)
    return rounding_fn(value)


def calculate_regular_fare(rate, distance):
    """Compute the regular (undiscounted) fare for one distance.

    `rate` is a dict from the fare_rates table. `distance` is in kilometers.
    Returns a breakdown dict including the rounded regular fare and flags
    telling whether a minimum/maximum fare was applied.
    """
    method = rate["fare_method"]

    if method == "base_succeeding":
        base_distance = _maybe_float(rate.get("base_distance")) or 0.0
        base_fare = _maybe_float(rate.get("base_fare")) or 0.0
        succeeding_rate = _maybe_float(rate.get("succeeding_rate")) or 0.0

        if distance <= base_distance:
            regular = base_fare
        else:
            extra_km = distance - base_distance
            regular = base_fare + (extra_km * succeeding_rate)

    elif method == "per_km":
        per_km_rate = _maybe_float(rate.get("per_km_rate")) or 0.0
        regular = distance * per_km_rate

    else:
        raise FareCalculationError(f"Unsupported fare method: {method}")

    # Optional minimum / maximum clamps.
    minimum_fare = _maybe_float(rate.get("minimum_fare"))
    maximum_fare = _maybe_float(rate.get("maximum_fare"))

    minimum_applied = minimum_fare is not None and regular < minimum_fare
    if minimum_applied:
        regular = minimum_fare

    maximum_applied = maximum_fare is not None and regular > maximum_fare
    if maximum_applied:
        regular = maximum_fare

    regular_fare = round(apply_rounding(regular, rate.get("rounding_rule")), 2)

    return {
        "regular_fare": regular_fare,
        "minimum_fare_applied": minimum_applied,
        "maximum_fare_applied": maximum_applied,
        "rounding_rule": rate.get("rounding_rule"),
    }


def calculate_discount(regular_fare, discount_percentage):
    """Return (discount_amount, final_fare) for a discounted passenger."""
    discount_percentage = _maybe_float(discount_percentage) or 0.0
    discount_amount = round(regular_fare * discount_percentage / 100.0, 2)
    final_fare = round(regular_fare - discount_amount, 2)
    return discount_amount, final_fare


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

def _require_id(raw, label):
    """Turn `raw` into a positive integer id or raise a friendly error."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise FareCalculationError(f"Please choose a valid {label}.")
    if value <= 0:
        raise FareCalculationError(f"Please choose a valid {label}.")
    return value


def validate_distance(raw):
    """Validate a distance value and return it as a rounded float (km)."""
    try:
        distance = round(float(raw), 2)
    except (TypeError, ValueError):
        raise FareCalculationError("Distance must be a number.")
    if distance <= 0:
        raise FareCalculationError("Distance must be greater than zero.")
    if distance > MAX_DISTANCE_KM:
        raise FareCalculationError(f"Distance cannot exceed {MAX_DISTANCE_KM} km.")
    return distance


def _optional_text(raw, max_len=100):
    """Trim an optional place name; empty becomes None (column is NULL)."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text[:max_len] or None


def _optional_coordinate(raw, label, min_value, max_value):
    """Validate an optional coordinate; None is allowed (column stays NULL)."""
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise FareCalculationError(f"Invalid {label}.")
    if not (min_value <= value <= max_value):
        raise FareCalculationError(f"Invalid {label}.")
    return value


def _optional_duration(raw):
    """Validate an optional travel duration in seconds; None is allowed."""
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise FareCalculationError("Invalid estimated duration.")
    if value < 0:
        raise FareCalculationError("Invalid estimated duration.")
    return value


# ---------------------------------------------------------------------------
# Database-driven orchestrator
# ---------------------------------------------------------------------------

def _get_current_fare_rate(cursor, transport_type_id):
    """Fetch the current active fare rate for a transport type."""
    cursor.execute(
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
    return cursor.fetchone()


def _load_and_compute(
    transport_type_id,
    passenger_type_id,
    distance,
    origin_name=None,
    destination_name=None,
    origin_latitude=None,
    origin_longitude=None,
    destination_latitude=None,
    destination_longitude=None,
    estimated_duration=None,
):
    """Validate inputs, resolve DB records, and compute the breakdown.

    The route metadata (`origin_*`, `destination_*`, `estimated_duration`) is
    optional and comes from the map when the fare comes from a route. Each
    field is validated and left as NULL when absent.

    Returns the full breakdown dict (without a persisted calculation_id).
    Raises FareCalculationError for any rule/preference violation.
    """
    distance = validate_distance(distance)
    transport_type_id = _require_id(transport_type_id, "transportation type")
    passenger_type_id = _require_id(passenger_type_id, "passenger type")

    # Optional route metadata — validated, coerced, or left as NULL.
    origin_name = _optional_text(origin_name)
    destination_name = _optional_text(destination_name)
    origin_latitude = _optional_coordinate(origin_latitude, "origin coordinates", -90, 90)
    origin_longitude = _optional_coordinate(origin_longitude, "origin coordinates", -180, 180)
    destination_latitude = _optional_coordinate(
        destination_latitude, "destination coordinates", -90, 90
    )
    destination_longitude = _optional_coordinate(
        destination_longitude, "destination coordinates", -180, 180
    )
    estimated_duration = _optional_duration(estimated_duration)

    db = get_db()
    with db.cursor() as cur:
        # 1. Active transportation type
        cur.execute(
            "SELECT id, name FROM transport_types WHERE id = %s AND status = 'active'",
            (transport_type_id,),
        )
        transport = cur.fetchone()
        if transport is None:
            raise FareCalculationError(
                "The selected transportation type is not available."
            )

        # 2. Active passenger type
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

        # 3. Current fare rule for this transport type
        rate = _get_current_fare_rate(cur, transport_type_id)
        if rate is None:
            raise FareCalculationError(
                "No active fare rate is configured for this transportation type."
            )

        # 4. Compute the regular fare and the discount
        breakdown = calculate_regular_fare(rate, distance)
        discount_percentage = _maybe_float(passenger["discount_percentage"]) or 0.0
        discount_amount, final_fare = calculate_discount(
            breakdown["regular_fare"], discount_percentage
        )

    return {
        "transport_type_id": transport_type_id,
        "transport_type": transport["name"],
        "passenger_type_id": passenger_type_id,
        "passenger_type": passenger["name"],
        "distance_km": distance,
        "fare_method": rate["fare_method"],
        "base_distance": _maybe_float(rate.get("base_distance")),
        "base_fare": _maybe_float(rate.get("base_fare")),
        "succeeding_rate": _maybe_float(rate.get("succeeding_rate")),
        "per_km_rate": _maybe_float(rate.get("per_km_rate")),
        "minimum_fare": _maybe_float(rate.get("minimum_fare")),
        "maximum_fare": _maybe_float(rate.get("maximum_fare")),
        "minimum_fare_applied": breakdown["minimum_fare_applied"],
        "maximum_fare_applied": breakdown["maximum_fare_applied"],
        "rounding_rule": rate["rounding_rule"],
        "source_reference": rate.get("source_reference"),
        "regular_fare": breakdown["regular_fare"],
        "discount_percentage": discount_percentage,
        "discount_amount": discount_amount,
        "final_fare": final_fare,
        "origin_name": origin_name,
        "destination_name": destination_name,
        "origin_latitude": origin_latitude,
        "origin_longitude": origin_longitude,
        "destination_latitude": destination_latitude,
        "destination_longitude": destination_longitude,
        "estimated_duration": estimated_duration,
    }


def compute_fare(
    transport_type_id,
    passenger_type_id,
    distance,
    origin_name=None,
    destination_name=None,
    origin_latitude=None,
    origin_longitude=None,
    destination_latitude=None,
    destination_longitude=None,
    estimated_duration=None,
):
    """Compute a fare breakdown without saving anything to history.

    Used by the live rate preview. Shares the exact engine path with
    `calculate_fare`, so previews always match the finalized result.
    """
    return _load_and_compute(
        transport_type_id,
        passenger_type_id,
        distance,
        origin_name=origin_name,
        destination_name=destination_name,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
        destination_latitude=destination_latitude,
        destination_longitude=destination_longitude,
        estimated_duration=estimated_duration,
    )


def calculate_fare(
    transport_type_id,
    passenger_type_id,
    distance,
    origin_name=None,
    destination_name=None,
    origin_latitude=None,
    origin_longitude=None,
    destination_latitude=None,
    destination_longitude=None,
    estimated_duration=None,
):
    """Full fare calculation: compute the breakdown, then save it to history.

    Returns a breakdown dict (including the stored calculation_id) ready to
    be returned as JSON.
    Raises FareCalculationError for any rule/preference violation.
    """
    payload = _load_and_compute(
        transport_type_id,
        passenger_type_id,
        distance,
        origin_name=origin_name,
        destination_name=destination_name,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
        destination_latitude=destination_latitude,
        destination_longitude=destination_longitude,
        estimated_duration=estimated_duration,
    )

    # 5. Save the calculation to history (guest records, no user)
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO fare_calculations
                (transport_type_id, passenger_type_id, distance,
                 regular_fare, discount_percentage, discount_amount, final_fare,
                 origin_name, destination_name,
                 origin_latitude, origin_longitude,
                 destination_latitude, destination_longitude,
                 estimated_duration)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                payload["transport_type_id"],
                payload["passenger_type_id"],
                payload["distance_km"],
                payload["regular_fare"],
                payload["discount_percentage"],
                payload["discount_amount"],
                payload["final_fare"],
                payload["origin_name"],
                payload["destination_name"],
                payload["origin_latitude"],
                payload["origin_longitude"],
                payload["destination_latitude"],
                payload["destination_longitude"],
                payload["estimated_duration"],
            ),
        )
        payload["calculation_id"] = cur.lastrowid

    return payload