# FareCal — Web-Based Public Transportation Fare Calculator

FareCal is a web application for calculating **estimated** public transportation
fares in the Philippines. It is built with Flask, MySQL, Bootstrap 5, and
vanilla JavaScript.

> **Important:** FareCal provides *estimated* fare calculations based on the fare
> rates configured in the system. Actual fares may vary depending on applicable
> transportation regulations, route conditions, fare adjustments, and other
> authorized charges. Initial fare data shipped with the app may be **SAMPLE/test
> data** (`source_reference = 'SAMPLE test data'`) and must not be treated as
> official fare information.

## Features

- **Fare calculator** — pick a transport type, passenger type (discounts
  applied automatically), and distance; get an instant estimate.
- **Accounts** — register, log in/out, change password, delete your account.
- **Personal dashboard** — quick stats and your most recent calculations.
- **History** — browse your saved calculations with search and pagination, and
  export them as CSV.
- **Admin panel** — manage users, transport types, fare rates, passenger
  types, and all saved calculations. Delete actions are protected by foreign-key
  guardrails (e.g. a transport type is not deletable while calculations
  reference it).
- **Security** — password hashing (Werkzeug), CSRF protection on all HTML
  forms, role-based access control.

## Technology Stack

- **Frontend:** HTML5, CSS3, Bootstrap 5 (local copy), Vanilla JavaScript
- **Backend:** Python 3, Flask (blueprints)
- **Database:** MySQL (PyMySQL connector)
- **Testing:** Python `unittest` (engine unit tests + route/integration tests)
- **Environment:** VS Code, Python virtual environment, Git/GitHub

## Project Structure

```
FareCal/
├── app.py                  # Entry point — creates and runs the Flask app
├── config.py               # Reads configuration from .env
├── requirements.txt
├── .env / .env.example     # Secrets live only in .env (gitignored)
├── database/
│   ├── connection.py       # PyMySQL connection helper
│   ├── schema.sql          # Database schema + sample seed data
│   ├── setup_db.py         # Creates the database and default admin
│   └── (optional)         # e.g. load_official_rates.py data-loading scripts
├── routes/                 # Flask blueprints (auth, fare, user, admin)
├── services/               # Business logic (fare_calculator.py)
├── templates/              # Jinja2 templates (incl. admin/ layout)
├── static/                 # CSS, JS, favicon, Bootstrap vendor files
└── tests/                  # unittest suites:
    ├── test_fare_calculator.py   # pure fare-engine tests (no DB)
    └── test_routes.py            # Flask-client integration tests (needs MySQL)
```

## Setup Instructions (Windows PowerShell)

### 1. Create the virtual environment and install dependencies

```powershell
cd C:\Users\Vin\OneDrive\Desktop\FareCal
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configure the environment

```powershell
Copy-Item .env.example .env
```

Open `.env` and set your MySQL credentials (especially `DB_PASSWORD`), and
change `SECRET_KEY` to a random string.

### 3. Create the database, tables, and sample data

```powershell
python database\setup_db.py
```

This is safe to re-run. It creates the `farecal_db` database, all tables,
sample transport types, passenger types, sample fare rates, and a default
administrator account:

- **Email:** `admin@farecal.ph`
- **Password:** `admin123`

> Change this password after your first login (Account → Change password).

### 4. Run the application

```powershell
python app.py
```

Open <http://127.0.0.1:5000> in your browser.

## Running the tests

```powershell
$env:PYTHONPATH = "C:\Users\Vin\OneDrive\Desktop\FareCal"

# Fare engine tests (no database required)
python -m unittest tests.test_fare_calculator

# Route/integration tests (requires a running MySQL + configured .env;
# uses the real farecal_db and cleans up its own temporary data)
python -m unittest tests.test_routes

# Full suite
python -m unittest discover -s tests
```

## Configuration (.env)

| Variable          | Description                                      |
|-------------------|--------------------------------------------------|
| `SECRET_KEY`      | Flask session secret (change this)               |
| `DB_HOST`         | MySQL host (default `localhost`)                 |
| `DB_PORT`         | MySQL port (default `3306`)                      |
| `DB_NAME`         | Database name (default `farecal_db`)             |
| `DB_USER`         | MySQL user (default `root`)                      |
| `DB_PASSWORD`     | MySQL password                                   |
| `ADMIN_EMAIL`     | Default admin email used by setup_db.py          |
| `ADMIN_PASSWORD`  | Default admin password used by setup_db.py       |

## Development Notes

- Fare rates are **database-driven** — never hard-coded in the frontend.
- Different transport types can use different fare structures (base + succeeding,
  per-kilometer, etc.) via the `fare_method` column.
- The database is created by `database\setup_db.py`; you do not need to run SQL
  manually.
- Deleting a user sets their past calculations to "Guest"
  (`FOREIGN KEY ... ON DELETE SET NULL`); deleting a transport type that still
  has calculations is intentionally blocked.