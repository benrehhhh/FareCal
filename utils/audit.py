"""Audit log helper — records significant security/admin events."""

from datetime import datetime

import pymysql
from flask import request

from database.connection import get_db


def log_audit(user_id, action, target_type=None, target_id=None, details=None):
    """Insert one row into the audit log.

    `user_id` is the actor (None when there is no logged-in session).
    `action` is a short verb like 'user.reset_password'. Target info is
    optional and used to identify what the action affected. `details`
    must stay under 255 characters (the schema column limit).
    """
    db = get_db()
    ip_address = request.remote_addr or ""

    with db.cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO audit_log
                    (user_id, action, target_type, target_id, details, ip_address)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    action,
                    target_type,
                    target_id,
                    details[:255] if details else None,
                    ip_address,
                ),
            )
        except pymysql.err.IntegrityError:
            # The actor no longer exists (deleted during this request) —
            # keep the event with a NULL actor rather than losing it.
            cur.execute(
                """
                INSERT INTO audit_log
                    (user_id, action, target_type, target_id, details, ip_address)
                VALUES (NULL, %s, %s, %s, %s, %s)
                """,
                (
                    action,
                    target_type,
                    target_id,
                    details[:255] if details else None,
                    ip_address,
                ),
            )
        db.commit()