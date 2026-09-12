"""Load researched LTFRB fare figures into FareCal.

Behavior:
  - Non-destructive: existing active fares for a transport type are set to
    'inactive' (rows are kept, with an expiration date) rather than deleted.
  - The current official rate is upserted with a `source_reference` citation.
  - Safe to re-run (idempotent).

Fetching official fares:
  Figures below were researched from news/orders in March 2026:
    - LTFRB order (Mar 17, 2026, effective Mar 19, 2026): jeepneys and buses
    - LTFRB order (Mar 18, 2024): regular taxi P50 nationwide flag-down
    - UV Express: standing per-km basis rounded per route; its fare hike
      petition was still under deliberation as of Mar 2026.

Run from the project root:
    python database\\load_official_rates.py
"""

from database.connection import get_connection

OFFICIAL_RATES = [
    {
        "transport": "Traditional PUJ",
        "fare_method": "base_succeeding",
        "base_distance": 4.0,
        "base_fare": 14.0,
        "succeeding_rate": 2.0,
        "rounding_rule": "round_up_025",
        "effective_date": "2026-03-19",
        "source_reference": (
            "LTFRB fare order Mar 17, 2026: traditional PUJ minimum P14 "
            "(first 4 km) + P2.00 per succeeding km; effective Mar 19, 2026"
        ),
    },
    {
        "transport": "Modernized PUJ",
        "fare_method": "base_succeeding",
        "base_distance": 4.0,
        "base_fare": 17.0,
        "succeeding_rate": 2.40,
        "rounding_rule": "round_up_025",
        "effective_date": "2026-03-19",
        "source_reference": (
            "LTFRB order Mar 17, 2026: modernized PUJ minimum P17 (first 4 km) "
            "+ P2.40 per succeeding km; eff. Mar 19, 2026 (P2.40 per "
            "GMA/SunStar, P2.30 per Manila Bulletin)"
        ),
    },
    {
        "transport": "Bus",
        "fare_method": "base_succeeding",
        "base_distance": 5.0,
        "base_fare": 15.0,
        "succeeding_rate": 2.49,
        "rounding_rule": "round_up_1",
        "effective_date": "2026-03-19",
        "source_reference": (
            "LTFRB fare order Mar 17, 2026: Metro/city ordinary bus minimum "
            "P15 (first 5 km) + P2.49 per succeeding km; effective Mar 19, 2026"
        ),
    },
    {
        "transport": "Taxi",
        "fare_method": "base_succeeding",
        "base_distance": 0.5,
        "base_fare": 50.0,
        "succeeding_rate": 45.0,
        "rounding_rule": "round_up_1",
        "effective_date": "2024-03-18",
        "source_reference": (
            "LTFRB order Mar 18, 2024: regular taxi flag-down P50 (first "
            "0.5 km) with succeeding charge ~P13.50 per 300 m (~P45/km); "
            "regular taxis were excluded from the Mar 19, 2026 increase"
        ),
    },
    {
        "transport": "UV Express",
        "fare_method": "per_km",
        "per_km_rate": 2.40,
        "minimum_fare": 28.0,
        "rounding_rule": "round_up_1",
        "effective_date": "2026-03-11",
        "source_reference": (
            "UV Express: no national flat minimum; ~P2.40/km for traditional "
            "units (GMA News, Mar 11, 2026) + LTFRB route-matrix minimums "
            "(lowest ~P28); hike petition pending as of Mar 2026"
        ),
    },
]


def load_official_rates():
    db = get_connection()
    try:
        with db.cursor() as cur:
            for rule in OFFICIAL_RATES:
                transport = rule["transport"]
                effective_date = rule["effective_date"]

                cur.execute(
                    "SELECT id FROM transport_types WHERE name = %s",
                    (transport,),
                )
                found = cur.fetchone()
                if found is None:
                    print(f"SKIPPED  {transport} (no such transport type)")
                    continue
                tt_id = found["id"]

                cur.execute(
                    """
                    UPDATE fare_rates
                    SET status = 'inactive',
                        expiration_date = COALESCE(
                            expiration_date,
                            DATE_SUB(%s, INTERVAL 1 DAY))
                    WHERE transport_type_id = %s AND status = 'active'
                    """,
                    (effective_date, tt_id),
                )
                deactivated = cur.rowcount

                # Per-column values (None columns are left untouched on
                # duplicate reloads).
                cur.execute(
                    """
                    INSERT INTO fare_rates
                        (transport_type_id, fare_method, base_distance,
                         base_fare, succeeding_rate, per_km_rate, minimum_fare,
                         maximum_fare, rounding_rule, effective_date,
                         expiration_date, status, source_reference)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL,
                            'active', %s)
                    ON DUPLICATE KEY UPDATE
                        fare_method = VALUES(fare_method),
                        base_distance = VALUES(base_distance),
                        base_fare = VALUES(base_fare),
                        succeeding_rate = VALUES(succeeding_rate),
                        per_km_rate = VALUES(per_km_rate),
                        minimum_fare = VALUES(minimum_fare),
                        maximum_fare = VALUES(maximum_fare),
                        rounding_rule = VALUES(rounding_rule),
                        status = 'active',
                        expiration_date = NULL,
                        source_reference = VALUES(source_reference)
                    """,
                    (
                        tt_id,
                        rule["fare_method"],
                        rule.get("base_distance"),
                        rule.get("base_fare"),
                        rule.get("succeeding_rate"),
                        rule.get("per_km_rate"),
                        rule.get("minimum_fare"),
                        rule.get("maximum_fare"),
                        rule["rounding_rule"],
                        effective_date,
                        rule["source_reference"],
                    ),
                )
                action = "UPSERTED" if deactivated == 0 else "LOADED"
                print(
                    f"{action:8s} {transport}  (eff {effective_date}) "
                    f"[deactivated {deactivated} old active rate(s)]"
                )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    load_official_rates()