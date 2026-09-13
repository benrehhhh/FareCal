"""WSGI entry point for production servers (Gunicorn, PythonAnywhere).

Used by the Procfile (gunicorn wsgi:app) and documented in README.md for
standalone WSGI hosts.
"""

from app import app as application

if __name__ == "__main__":
    application.run()