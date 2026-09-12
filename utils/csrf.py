"""Lightweight CSRF protection using the Flask session.

Every HTML form includes a hidden `_csrf_token` field (via the `csrf_token()`
template global). On form POSTs, the server compares the submitted token with
the one stored in the session using a constant-time comparison.
"""

import secrets

from flask import request, session


def generate_csrf_token():
    """Create (or reuse) the CSRF token for the current session."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]


def validate_csrf_token():
    """True when the submitted token matches the session token."""
    submitted = request.form.get("_csrf_token")
    expected = session.get("_csrf_token")
    if not submitted or not expected:
        return False
    return secrets.compare_digest(submitted, expected)