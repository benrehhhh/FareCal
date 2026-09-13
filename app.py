"""Main entry point for the FareCal Flask application.

The application factory registers the fare/calculator blueprint and serves
the homepage calculator. Stay slim: FareCal is a single-purpose fare-per-km
calculator, so only the calculator features live here.
"""

from flask import Flask, jsonify, render_template, request

from config import Config
from database.connection import close_db, test_connection
from routes.fare import fare_bp
from utils.csrf import validate_csrf_token


def create_app(config_class=Config):
    """Application factory — builds and configures the Flask app."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Close the database connection when a request ends.
    app.teardown_appcontext(close_db)

    # Blueprints (routes are grouped by area — see the routes/ folder).
    app.register_blueprint(fare_bp)

    @app.template_filter("peso")
    def format_peso(value):
        """Format a numeric value as Philippine pesos, e.g. 24.0 -> ₱24.00."""
        if value is None or value == "":
            return "—"
        try:
            return f"₱{float(value):,.2f}"
        except (TypeError, ValueError):
            return "—"

    @app.before_request
    def protect_against_csrf():
        """Validate the CSRF token on HTML form POSTs.

        JSON/API POSTs (paths starting with /api/) are exempt because they use
        a different request format and the public calculator is guest-accessible.
        """
        if request.method == "POST" and request.path.startswith("/api/"):
            return None
        if request.method == "POST" and not validate_csrf_token():
            return (
                render_template(
                    "error.html",
                    code=400,
                    message="Your form session expired. Please submit the form again.",
                ),
                400,
            )
        return None

    @app.route("/healthz")
    def healthz():
        """Health check for platform health monitors (Render, Railway, etc.).

        Returns 200 when MySQL is reachable, 503 otherwise.
        """
        status = test_connection()
        code = 200 if status["ok"] else 503
        return jsonify(
            {
                "status": "ok" if status["ok"] else "error",
                "db": status["table_count"],
            }
        ), code

    # --- Public pages ----------------------------------------------------

    @app.route("/")
    def index():
        """Homepage — the public fare calculator."""
        return render_template("index.html")

    # --- Friendly error pages ------------------------------------------

    ERR_MESSAGES = {
        400: "The request was not valid.",
        403: "You do not have permission to access this page.",
        404: "The page you are looking for was not found.",
        500: "Something went wrong on our side. Please try again.",
    }

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(500)
    def handle_http_error(error):
        code = getattr(error, "code", 500)
        message = ERR_MESSAGES.get(code, "An error occurred.")
        return render_template("error.html", code=code, message=message), code

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)