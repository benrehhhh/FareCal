"""FareCal configuration.

Loads all settings from the .env file (see .env.example for the template).
No secrets are hard-coded here.
"""

import os

from dotenv import load_dotenv

# Load variables from the .env file located in the project root.
load_dotenv()


class Config:
    """Application configuration, read from environment variables."""

    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    # Cookie security — set SESSION_COOKIE_SECURE=true behind HTTPS
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"

    # MySQL connection settings
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_NAME = os.getenv("DB_NAME", "farecal_db")
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")

    # Fare calculator limits
    MAX_DISTANCE_KM = int(os.getenv("MAX_DISTANCE_KM", "500"))


MAX_DISTANCE_KM = Config.MAX_DISTANCE_KM