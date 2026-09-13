"""Database setup script.

Creates the farecal_db database, all tables, and sample seed data. It does
not create user accounts — FareCal is a calculator-only app. Reads MySQL
credentials from .env.

Safe to run multiple times — existing rows are preserved.

Usage:
    python database\\setup_db.py
"""

import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "farecal_db")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

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


ROUTE_COLUMNS = {
    "origin_name": "VARCHAR(100) NULL",
    "destination_name": "VARCHAR(100) NULL",
    "origin_latitude": "DECIMAL(10, 7) NULL",
    "origin_longitude": "DECIMAL(10, 7) NULL",
    "destination_latitude": "DECIMAL(10, 7) NULL",
    "destination_longitude": "DECIMAL(10, 7) NULL",
    "estimated_duration": "INT UNSIGNED NULL",
}


def ensure_route_columns(conn):
    """Add route-metadata columns to a fare/history table if missing.

    MySQL has no `ADD COLUMN IF NOT EXISTS`, so inspect information_schema
    and ALTER only the columns that are absent. Safe to run repeatedly;
    existing rows are preserved.
    """
    for table in ("fare_calculations",):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COLUMN_NAME
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                """,
                (DB_NAME, table),
            )
            existing = {row["COLUMN_NAME"] for row in cur.fetchall()}
            for name, definition in ROUTE_COLUMNS.items():
                if name in existing:
                    continue
                cur.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                )
                print(f"[setup] Added {table}.{name}")
    conn.commit()


def report_counts(conn):
    """Print a short summary of seeded data so the result is visible."""
    table = {
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
        ensure_route_columns(conn)
        report_counts(conn)
        print(f"[setup] Done. Database '{DB_NAME}' is ready.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()