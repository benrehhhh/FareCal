"""Access-control decorators for Flask routes."""

from functools import wraps

from flask import abort, redirect, session, url_for


def login_required(view):
    """Require an authenticated user; otherwise send them to the login page."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """Require an administrator account; otherwise redirect or show 403."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped