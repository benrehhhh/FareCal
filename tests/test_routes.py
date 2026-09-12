"""Integration tests for the FareCal Flask routes.

Requires a running MySQL (see .env) — the tests exercise the real
`farecal_db`. Every test cleans up the temporary records it creates, so the
suite is safe to run repeatedly.

Run from the project root:
    python -m unittest discover -s tests -v
"""

import unittest

from werkzeug.security import generate_password_hash

from app import app
from database.connection import get_connection

TEMP_USER = "it-user@farecal.ph"
TEMP_PASSWORD = "password1234"
ADMIN_EMAIL = "admin@farecal.ph"
ADMIN_PASSWORD = "admin123"


class RouteTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    # ------------------------------------------------------------ helpers
    def _cleanup(self):
        """Remove every temporary record this suite may have created."""
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM fare_calculations WHERE user_id IN "
                "(SELECT id FROM users WHERE email = %s)",
                (TEMP_USER,),
            )
            cur.execute("DELETE FROM users WHERE email = %s", (TEMP_USER,))
            cur.execute(
                "DELETE FROM fare_calculations WHERE transport_type_id IN "
                "(SELECT id FROM transport_types WHERE name LIKE 'IT TEST %%')"
            )
            cur.execute("DELETE FROM transport_types WHERE name LIKE 'IT TEST %%'")
            cur.execute("DELETE FROM passenger_types WHERE name LIKE 'IT PASS %%'")
            cur.execute(
                "DELETE FROM routes WHERE origin LIKE 'IT TEST %%' "
                "OR destination LIKE 'IT TEST %%'"
            )
        conn.close()

    def _csrf(self, page):
        """GET a page that renders a CSRF hidden input, then return its token."""
        self.client.get(page)
        with self.client.session_transaction() as sess:
            return sess["_csrf_token"]

    def _post(self, url, data, token_page):
        """POST an HTML form with a CSRF token (token seeded from token_page)."""
        payload = dict(data)
        payload["_csrf_token"] = self._csrf(token_page)
        return self.client.post(url, data=payload)

    def _login(self, email, password):
        return self._post("/login", {"email": email, "password": password}, "/login")

    def _login_as_temp_user(self):
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (name, email, password_hash, role) "
                "VALUES (%s, %s, %s, 'user')",
                ("IT User", TEMP_USER, generate_password_hash(TEMP_PASSWORD)),
            )
        conn.close()
        response = self._login(TEMP_USER, TEMP_PASSWORD)
        self.assertEqual(response.status_code, 302)

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

    # ------------------------------------------------------- public pages
    def test_index_renders_calculator(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Fare Calculator", response.get_data(as_text=True))

    def test_login_and_register_pages_render(self):
        for path in ("/login", "/register"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)

    # ------------------------------------------------------------ auth
    def test_register_validates_and_logs_in_fresh_user(self):
        response = self._post(
            "/register",
            {"name": "IT User", "email": TEMP_USER,
             "password": TEMP_PASSWORD, "confirm_password": TEMP_PASSWORD},
            "/register",
        )
        self.assertEqual(response.status_code, 302)
        response = self._login(TEMP_USER, TEMP_PASSWORD)
        self.assertEqual(response.status_code, 302)

    def test_register_rejects_wrong_confirmation(self):
        response = self._post(
            "/register",
            {"name": "IT User", "email": TEMP_USER,
             "password": TEMP_PASSWORD, "confirm_password": "different99"},
            "/register",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("do not match", response.get_data(as_text=True).lower())

    def test_register_rejects_duplicate_email(self):
        self._login_as_temp_user()
        self._post("/logout", {}, "/account")
        response = self._post(
            "/register",
            {"name": "IT User 2", "email": TEMP_USER,
             "password": TEMP_PASSWORD, "confirm_password": TEMP_PASSWORD},
            "/register",
        )
        body = response.get_data(as_text=True)
        self.assertIn("already registered", body)

    def test_login_rejects_wrong_password(self):
        self._login_as_temp_user()
        self._post("/logout", {}, "/account")
        response = self._login(TEMP_USER, "wrongpassword")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid email or password", response.get_data(as_text=True))

    def test_login_sets_session_and_logout_clears_it(self):
        self._login_as_temp_user()
        with self.client.session_transaction() as sess:
            self.assertIsNotNone(sess.get("user_id"))
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

        self._post("/logout", {}, "/account")
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))

    def test_html_forms_require_csrf_token(self):
        response = self.client.post("/login", data={"email": TEMP_USER, "password": TEMP_PASSWORD})
        self.assertEqual(response.status_code, 400)

    # ------------------------------------------------------------- APIs
    def test_api_transport_types(self):
        response = self.client.get("/api/transport-types")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertGreater(len(response.get_json()["result"]), 0)

    def test_api_passenger_types(self):
        response = self.client.get("/api/passenger-types")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])

    def test_api_calculate_fare_valid(self):
        self._login_as_temp_user()  # so the saved calculation is cleaned up
        t, p = self._active_ids()
        response = self.client.post(
            "/api/calculate-fare",
            json={"transport_type_id": t, "passenger_type_id": p, "distance": 5},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertGreater(data["result"]["final_fare"], 0)

    def test_api_calculate_fare_rejects_invalid_distance(self):
        self._login_as_temp_user()
        t, p = self._active_ids()
        response = self.client.post(
            "/api/calculate-fare",
            json={"transport_type_id": t, "passenger_type_id": p, "distance": -1},
        )
        self.assertEqual(response.status_code, 400)

    def test_api_calculate_fare_rejects_unknown_transport(self):
        self._login_as_temp_user()
        _, p = self._active_ids()
        response = self.client.post(
            "/api/calculate-fare",
            json={"transport_type_id": 999999, "passenger_type_id": p, "distance": 5},
        )
        self.assertEqual(response.status_code, 400)

    # ------------------------------------------------ access control
    def test_protected_pages_require_login(self):
        for path in ("/dashboard", "/history", "/account", "/history/export"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)

    def test_admin_pages_block_regular_users(self):
        self._login_as_temp_user()
        for path in ("/admin", "/admin/users", "/admin/transport-types",
                     "/admin/fare-rates", "/admin/passenger-types", "/admin/calculations"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403, path)

    def test_admin_pages_allow_admin(self):
        self._login(ADMIN_EMAIL, ADMIN_PASSWORD)
        for path in ("/admin", "/admin/users", "/admin/transport-types",
                     "/admin/fare-rates", "/admin/passenger-types", "/admin/calculations"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    # ---------------------------------------------------------- admin
    def test_admin_can_toggle_user(self):
        self._login_as_temp_user()
        self._post("/logout", {}, "/account")
        self._login(ADMIN_EMAIL, ADMIN_PASSWORD)

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, status FROM users WHERE email = %s", (TEMP_USER,))
                row = cur.fetchone()
                user_id, status = row["id"], row["status"]
        finally:
            conn.close()
        self.assertEqual(status, "active")

        self._post(f"/admin/users/{user_id}/toggle", {}, "/admin/users")
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM users WHERE id = %s", (user_id,))
                self.assertEqual(cur.fetchone()["status"], "inactive")
        finally:
            conn.close()

    def test_admin_can_delete_user(self):
        self._login_as_temp_user()
        self._post("/logout", {}, "/account")
        self._login(ADMIN_EMAIL, ADMIN_PASSWORD)

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE email = %s", (TEMP_USER,))
                user_id = cur.fetchone()["id"]
        finally:
            conn.close()

        self._post(f"/admin/users/{user_id}/delete", {}, "/admin/users")
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
                self.assertIsNone(cur.fetchone())
        finally:
            conn.close()

    def test_admin_add_and_edit_statuses_transport_type(self):
        self._login(ADMIN_EMAIL, ADMIN_PASSWORD)

        # Add
        self._post(
            "/admin/transport-types",
            {"name": "IT TEST Bus", "description": "added by integration test"},
            "/admin/transport-types",
        )
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM transport_types WHERE name = 'IT TEST Bus'")
                tt_id = cur.fetchone()["id"]
        finally:
            conn.close()

        # Duplicate add warns
        self._post(
            "/admin/transport-types",
            {"name": "IT TEST Bus", "description": ""},
            "/admin/transport-types",
        )
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) c FROM transport_types WHERE name = 'IT TEST Bus'")
                self.assertEqual(cur.fetchone()["c"], 1)
        finally:
            conn.close()

        # Toggle then delete
        self._post(f"/admin/transport-types/{tt_id}/toggle", {}, "/admin/transport-types")
        self._post(f"/admin/transport-types/{tt_id}/delete", {}, "/admin/transport-types")
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM transport_types WHERE id = %s", (tt_id,))
                self.assertIsNone(cur.fetchone())
        finally:
            conn.close()

    def test_admin_cannot_delete_referenced_transport(self):
        self._login(ADMIN_EMAIL, ADMIN_PASSWORD)

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO transport_types (name) VALUES ('IT TEST Guard')"
                )
                tt_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO fare_calculations (user_id, transport_type_id, "
                    "passenger_type_id, distance, regular_fare, final_fare) "
                    "VALUES (NULL, %s, 1, 3.0, 13.0, 13.0)",
                    (tt_id,),
                )
        finally:
            conn.close()

        self._post(f"/admin/transport-types/{tt_id}/delete", {}, "/admin/transport-types")
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM transport_types WHERE id = %s", (tt_id,))
                self.assertIsNotNone(cur.fetchone())  # blocked, still present
        finally:
            conn.close()
        # tearDown cleanup removes the calc + transport

    # ------------------------------------------------------ account
    def test_account_change_password(self):
        self._login_as_temp_user()

        self._post(
            "/account/change-password",
            {"current_password": TEMP_PASSWORD,
             "new_password": "newpass99", "confirm_password": "newpass99"},
            "/account",
        )
        self._post("/logout", {}, "/account")
        response = self._login(TEMP_USER, "newpass99")
        self.assertEqual(response.status_code, 302)

    def test_account_delete_requires_action(self):
        self._login_as_temp_user()
        self._post("/account/delete", {}, "/account")
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE email = %s", (TEMP_USER,))
                self.assertIsNone(cur.fetchone())
        finally:
            conn.close()
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))

    def test_admin_cannot_delete_own_account(self):
        self._login(ADMIN_EMAIL, ADMIN_PASSWORD)
        self._post("/account/delete", {}, "/account")
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE email = %s", (ADMIN_EMAIL,))
                self.assertIsNotNone(cur.fetchone())
        finally:
            conn.close()

    # ------------------------------------------------- public pages
    def test_fares_page_renders(self):
        response = self.client.get("/fares")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        for name in ("Traditional PUJ", "Modernized PUJ", "Bus", "Taxi"):
            self.assertIn(name, body)
        self.assertIn("LTFRB", body)

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

    # ------------------------------------------------------ account
    def test_account_page_renders(self):
        self._login_as_temp_user()
        body = self.client.get("/account").get_data(as_text=True)
        self.assertEqual(self.client.get("/account").status_code, 200)
        self.assertIn("Change Password", body)

    # ------------------------------------------------- history/export
    def test_history_search_and_export(self):
        self._login_as_temp_user()

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE email = %s", (TEMP_USER,))
                uid = cur.fetchone()["id"]
                cur.execute(
                    "SELECT id FROM transport_types WHERE status='active' "
                    "ORDER BY id LIMIT 2"
                )
                t1, t2 = [row["id"] for row in cur.fetchall()]
                _, passenger_id = self._active_ids()
                cur.execute(
                    "SELECT name FROM transport_types WHERE id = %s", (t1,)
                )
                t1_name = cur.fetchone()["name"]
                for t in (t1, t2):
                    cur.execute(
                        "INSERT INTO fare_calculations "
                        "(user_id, transport_type_id, passenger_type_id, distance, "
                        "regular_fare, final_fare) VALUES (%s, %s, %s, 5.0, 20.0, 20.0)",
                        (uid, t, passenger_id),
                    )
        finally:
            conn.close()

        # Site search filters by transport name.
        filter_term = t1_name.split()[0]
        html = self.client.get(f"/history?q={filter_term}").get_data(as_text=True)
        self.assertIn(t1_name, html)

        # CSV export lists both rows, honors the search filter, and is public-URL safe.
        body = self.client.get("/history/export").get_data(as_text=True)
        self.assertEqual(200, self.client.get("/history/export").status_code)
        self.assertIn("Transport", body.splitlines()[0])
        self.assertEqual(len(body.splitlines()) - 1, 2)

        one = self.client.get(f"/history/export?q={filter_term}").get_data(as_text=True)
        self.assertEqual(len(one.splitlines()) - 1, 1)

        self._post("/logout", {}, "/account")
        self.assertEqual(self.client.get("/history/export").status_code, 302)

    # ------------------------------------------------------ admin routes
    def test_admin_routes_page_requires_admin(self):
        self.assertEqual(self.client.get("/admin/routes").status_code, 302)
        self._login_as_temp_user()
        self.assertEqual(self.client.get("/admin/routes").status_code, 403)

    def test_admin_routes_crud(self):
        self._login(ADMIN_EMAIL, ADMIN_PASSWORD)
        transport_id = self._active_ids()[0]

        self._post(
            "/admin/routes",
            {"transport_type_id": str(transport_id),
             "origin": "IT TEST One", "destination": "IT TEST Two",
             "distance_km": "4.75"},
            "/admin/routes",
        )
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM routes WHERE origin='IT TEST One' "
                    "AND destination='IT TEST Two'"
                )
                route_id = cur.fetchone()["id"]
        finally:
            conn.close()

        self._post(f"/admin/routes/{route_id}/toggle", {}, "/admin/routes")
        self._post(f"/admin/routes/{route_id}/delete", {}, "/admin/routes")

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM routes WHERE id = %s", (route_id,))
                self.assertIsNone(cur.fetchone())
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()