"""Database connection helpers using PyMySQL.

Every route gets a shared connection via Flask's app context (`g`),
which is automatically closed at the end of the request.
"""

import pymysql
import pymysql.cursors

from config import Config


def get_connection():
    """Create a new PyMySQL connection to the configured database."""
    return pymysql.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def get_db():
    """Return the database connection for the current request (or open one).

    Usage inside a route:
        from flask import g
        from database.connection import get_db
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT ...")
            rows = cur.fetchall()
    """
    from flask import g

    if "db" not in g:
        g.db = get_connection()
    return g.db


def close_db(exception=None):
    """Close the request-scoped database connection (called after each request)."""
    from flask import g

    db = g.pop("db", None)
    if db is not None:
        db.close()


def test_connection():
    """Check whether Flask can reach MySQL.

    Returns a dict:
        {"ok": bool, "table_count": int or None, "error": str or None}
    """
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS table_count
                    FROM information_schema.tables
                    WHERE table_schema = %s
                    """,
                    (Config.DB_NAME,),
                )
                row = cur.fetchone()
            return {"ok": True, "table_count": row["table_count"], "error": None}
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - converted to a friendly message
        return {"ok": False, "table_count": None, "error": str(exc)}