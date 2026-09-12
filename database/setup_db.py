"""Database setup script.

Creates the farecal_db database, all tables, sample seed data, and a
default administrator account. Reads MySQL credentials from .env.

Safe to run multiple times — existing rows are preserved.

Usage:
    python database\\setup_db.py
"""

import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "farecal_db")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@farecal.ph")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
ADMIN_NAME = os.getenv("ADMIN_NAME", "FareCal Administrator")

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def run_schema(conn):
    """Execute every statement in schema.sql against the connection."""
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()
    print(f"[setup] Schema executed: {len(statements)} statement(s)")


def seed_admin(conn):
    """Create the default administrator if it does not already exist."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (ADMIN_EMAIL,))
        if cur.fetchone():
            print(f"[setup] Admin '{ADMIN_EMAIL}' already exists - skipping.")
            return
        password_hash = generate_password_hash(ADMIN_PASSWORD)
        cur.execute(
            """
            INSERT INTO users (name, email, password_hash, role)
            VALUES (%s, %s, %s, 'admin')
            """,
            (ADMIN_NAME, ADMIN_EMAIL, password_hash),
        )
    conn.commit()
    print(f"[setup] Admin user created: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")


def report_counts(conn):
    """Print a short summary of seeded data so the result is visible."""
    table = {
        "users": "SELECT COUNT(*) AS c FROM users",
        "transport_types": "SELECT COUNT(*) AS c FROM transport_types",
        "passenger_types": "SELECT COUNT(*) AS c FROM passenger_types",
        "fare_rates": "SELECT COUNT(*) AS c FROM fare_rates",
        "fare_calculations": "SELECT COUNT(*) AS c FROM fare_calculations",
    }
    with conn.cursor() as cur:
        print("[setup] Row counts:")
        for label, query in table.items():
            cur.execute(query)
            print(f"[setup]   {label}: {cur.fetchone()['c']}")


def main():
    # Connect WITHOUT a database first — the schema creates it.
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
    except Exception as exc:  # noqa: BLE001 - user-facing friendly message
        print("-" * 60)
        print("[setup] ERROR: Could not connect to MySQL.")
        print(f"  {exc}")
        print("  Check DB_HOST / DB_PORT / DB_USER / DB_PASSWORD in your .env file.")
        print("-" * 60)
        sys.exit(1)

    try:
        print(f"[setup] Connected to MySQL on {DB_HOST}:{DB_PORT}")
        run_schema(conn)
        seed_admin(conn)
        report_counts(conn)
        print(f"[setup] Done. Database '{DB_NAME}' is ready.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()