"""Integration tests for the FareCal Flask routes.

FareCal is a calculator-only app — no accounts, no admin, no saved trips.
These tests cover the homepage render and the fare API surface only, and
clean up the guest calculation rows they create.

Requires a running MySQL (see .env) — the tests exercise the real
`farecal_db`. Run from the project root:
    python -m unittest discover -s tests -v
"""

import unittest

from app import app
from database.connection import get_connection


class RouteTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    # ------------------------------------------------------------ helpers
    def _cleanup(self):
        """Remove guest fare_calculations rows created by this suite."""
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM fare_calculations WHERE origin_name LIKE 'IT TEST %'"
            )
        conn.close()

    def _active_ids(self):
        """Return a (transport_type_id, passenger_type_id) pair from the seed."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM transport_types WHERE status='active' ORDER BY id LIMIT 1"
                )
                t = cur.fetchone()["id"]
                cur.execute(
                    "SELECT id FROM passenger_types WHERE status='active' ORDER BY id LIMIT 1"
                )
                p = cur.fetchone()["id"]
            return t, p
        finally:
            conn.close()

    def _calc_payload(self, t, p, distance=5, **overrides):
        payload = {
            "transport_type_id": t,
            "passenger_type_id": p,
            "distance": distance,
            "origin_name": "IT TEST Origin",
            "destination_name": "IT TEST Destination",
        }
        payload.update(overrides)
        return payload

    # --------------------------------------------------------- home page
    def test_index_renders_calculator(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Fare Calculator", response.get_data(as_text=True))

    def test_index_renders_breakdown_modal_and_total_box(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="fareBreakdownModal"', body)
        self.assertIn('id="totalFareBox"', body)
        self.assertNotIn('id="resultPanel"', body)
        self.assertNotIn("Coming in the next update", body)

    def test_home_is_calculator_only_nav(self):
        body = self.client.get("/").get_data(as_text=True)
        # Brand bar only: no account dropdown, no guest links, no admin badge.
        self.assertIn('href="/">', body)
        self.assertIn("FareCal", body)
        self.assertNotIn('id="navMenuButton"', body)
        self.assertNotIn('id="navMenuDropdown"', body)
        self.assertNotIn("Administration", body)
        self.assertNotIn("text-bg-warning", body)
        self.assertNotIn(">Logout<", body)
        self.assertNotIn(">Register<", body)
        self.assertNotIn('href="/fares"', body)
        # Calculator scaffolding is present.
        self.assertIn('id="calculateFareModal"', body)
        self.assertIn('id="openCalculateBtn"', body)
        self.assertIn("Calculate Your Fare", body)
        self.assertNotIn('id="fareForm"', body)

    def test_breakdown_modal_has_no_save_or_print_actions(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("Save this trip", body)
        self.assertNotIn("Print estimate", body)
        self.assertNotIn("window.print", body)
        self.assertNotIn('id="saveTripBtn"', body)
        self.assertNotIn('id="viewBreakdownBtn"', body)
        self.assertNotIn('id="currentFareModal"', body)

    def test_removed_pages_return_404(self):
        for path in (
            "/login",
            "/register",
            "/dashboard",
            "/history",
            "/history/export",
            "/account",
            "/fares",
            "/admin",
            "/admin/users",
            "/admin/transport-types",
            "/admin/fare-rates",
            "/admin/passenger-types",
            "/admin/routes",
            "/admin/calculations",
            "/admin/audit",
            "/api/saved-trips",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)

    def test_favicon_is_bus_icon(self):
        response = self.client.get("/static/favicon.svg")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('viewBox="0 0 64 64"', body)
        self.assertIn('stroke="#ffffff"', body)
        self.assertNotIn("text", body)

    # -------------------------------------------------------------- APIs
    def test_api_transport_types(self):
        response = self.client.get("/api/transport-types")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertGreater(len(response.get_json()["result"]), 0)

    def test_api_passenger_types(self):
        response = self.client.get("/api/passenger-types")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertGreater(len(response.get_json()["result"]), 0)

    def test_api_calculate_fare_valid(self):
        t, p = self._active_ids()
        response = self.client.post(
            "/api/calculate-fare",
            json=self._calc_payload(t, p, distance=5),
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertGreater(data["result"]["final_fare"], 0)

    def test_api_calculate_fare_stores_route_metadata(self):
        t, p = self._active_ids()
        response = self.client.post(
            "/api/calculate-fare",
            json=self._calc_payload(
                t,
                p,
                distance=5,
                origin_name="IT TEST Origin",
                destination_name="IT TEST Destination",
                origin_latitude=10.31179,
                origin_longitude=123.91867,
                destination_latitude=10.3154,
                destination_longitude=123.8951,
                estimated_duration=570,
            ),
        )
        self.assertEqual(response.status_code, 200)
        calc_id = response.get_json()["result"]["calculation_id"]

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT origin_name, destination_name,
                           origin_latitude, origin_longitude,
                           destination_latitude, destination_longitude,
                           estimated_duration
                    FROM fare_calculations
                    WHERE id = %s
                    """,
                    (calc_id,),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["origin_name"], "IT TEST Origin")
        self.assertEqual(row["destination_name"], "IT TEST Destination")
        self.assertAlmostEqual(float(row["origin_latitude"]), 10.31179, places=5)
        self.assertAlmostEqual(float(row["origin_longitude"]), 123.91867, places=5)
        self.assertAlmostEqual(float(row["destination_latitude"]), 10.3154, places=5)
        self.assertAlmostEqual(float(row["destination_longitude"]), 123.8951, places=5)
        self.assertEqual(row["estimated_duration"], 570)

    def test_api_calculate_fare_rejects_invalid_coordinates(self):
        t, p = self._active_ids()
        response = self.client.post(
            "/api/calculate-fare",
            json=self._calc_payload(t, p, origin_latitude=95, origin_longitude=200),
        )
        self.assertEqual(response.status_code, 400)

    def test_api_calculate_fare_rejects_invalid_distance(self):
        t, p = self._active_ids()
        response = self.client.post(
            "/api/calculate-fare",
            json=self._calc_payload(t, p, distance=-1),
        )
        self.assertEqual(response.status_code, 400)

    def test_api_calculate_fare_rejects_unknown_transport(self):
        _, p = self._active_ids()
        response = self.client.post(
            "/api/calculate-fare",
            json=self._calc_payload(999999, p, distance=5),
        )
        self.assertEqual(response.status_code, 400)

    def test_api_transport_rate_valid(self):
        t, _ = self._active_ids()
        response = self.client.get(f"/api/transport-types/{t}/rate")
        self.assertEqual(response.status_code, 200)
        rate = response.get_json()["result"]
        self.assertEqual(rate["transport_type_id"], t)
        self.assertIn(rate["fare_method"], ("base_succeeding", "per_km"))
        self.assertIsInstance(rate["base_fare"], float)
        self.assertIsInstance(rate["rounding_rule"], str)
        self.assertTrue(rate["effective_date"])
        self.assertTrue(rate["transport_name"])

    def test_api_transport_rate_unknown_transport(self):
        response = self.client.get("/api/transport-types/999999/rate")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["success"])

    def test_api_fare_preview_computes_without_history(self):
        t, p = self._active_ids()

        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM fare_calculations")
            before = cur.fetchone()["c"]

        response = self.client.post(
            "/api/fare-preview",
            json={"transport_type_id": t, "passenger_type_id": p, "distance": 5},
        )
        self.assertEqual(response.status_code, 200)
        result = response.get_json()["result"]
        self.assertNotIn("calculation_id", result)
        self.assertGreater(result["final_fare"], 0)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM fare_calculations")
            after = cur.fetchone()["c"]
        conn.close()
        self.assertEqual(after, before)

    def test_api_fare_preview_rejects_invalid_distance(self):
        t, p = self._active_ids()
        response = self.client.post(
            "/api/fare-preview",
            json={"transport_type_id": t, "passenger_type_id": p, "distance": -1},
        )
        self.assertEqual(response.status_code, 400)

    def test_api_routes_endpoint(self):
        data = self.client.get("/api/routes").get_json()
        self.assertTrue(data["success"])
        self.assertGreater(len(data["result"]), 0)

        tt_id = data["result"][0]["transport_type_id"]
        filtered = self.client.get(f"/api/routes?transport_id={tt_id}").get_json()
        self.assertTrue(filtered["success"])
        self.assertTrue(
            all(r["transport_type_id"] == tt_id for r in filtered["result"])
        )

        self.assertEqual(self.client.get("/api/routes?transport_id=abc").status_code, 400)


if __name__ == "__main__":
    unittest.main()