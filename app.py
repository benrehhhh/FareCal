"""Main entry point for the FareCal Flask application.

The application factory registers blueprints, wires up authentication
(sessions, CSRF, access control), and serves the homepage calculator.
"""

from flask import Flask, render_template, request, session

from config import Config
from database.connection import close_db
from routes.auth import auth_bp
from routes.fare import fare_bp
from utils.csrf import generate_csrf_token, validate_csrf_token


def create_app(config_class=Config):
    """Application factory — builds and configures the Flask app."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Close the database connection when a request ends.
    app.teardown_appcontext(close_db)

    # Blueprints (routes are grouped by area — see the routes/ folder).
    app.register_blueprint(auth_bp)
    app.register_blueprint(fare_bp)

    # Make the CSRF token helper available in every template.
    app.jinja_env.globals["csrf_token"] = generate_csrf_token

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

    @app.context_processor
    def inject_current_user():
        """Expose the logged-in user's profile to every template."""
        user = None
        if session.get("user_id"):
            user = {
                "id": session["user_id"],
                "name": session.get("name"),
                "email": session.get("email"),
                "role": session.get("role"),
            }
        return {"current_user": user}

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