# FareCal — Public Transportation Fare Calculator

FareCal estimates public-transportation fares in the Philippines from a per-km
fare structure. Built with Flask, MySQL, Bootstrap 5, and vanilla JavaScript —
a single-purpose calculator: pick a route, get the fare.

> **Disclaimer:** Estimates are based on configured rates. Initial data shipped
> with the app is SAMPLE/test data (`source_reference = 'SAMPLE test data'`)
> and is not official fare information.

## Features

- Map-based route building (search or tap the map), distance auto-filled
- Transportation types with configurable fare structures
  (base+per-km or pure per-km, min/max caps, rounding)
- Passenger discounts (students, seniors, PWD) applied automatically
- Common-route presets, live fare-rate preview, and a detailed breakdown modal
- Fare history recorded per calculation (guest rows)

## Tech Stack

| Layer    | Technology                                                        |
|----------|-------------------------------------------------------------------|
| Frontend | HTML5, CSS3, Bootstrap 5 (vendored), vanilla JS, Leaflet + OSM/Nominatim/OSRM |
| Backend  | Python 3, Flask, PyMySQL                                          |
| Testing  | `unittest` — fare engine unit tests + route integration tests     |

## Project Structure

```
FareCal/
├── app.py                     # Flask app factory + /healthz
├── wsgi.py                    # Gunicorn / PythonAnywhere entry point
├── config.py                  # Reads settings from .env
├── requirements.txt
├── .env.example               # Copy to .env and fill in your values
├── database/
│   ├── connection.py          # PyMySQL connection helper
│   ├── schema.sql             # Tables + sample seed data
│   ├── setup_db.py            # Creates the database, tables, and seeds
│   └── load_official_rates.py # Loads current LTFRB published rates
├── routes/
│   └── fare.py                # Fare calculator API endpoints
├── services/
│   └── fare_calculator.py     # Fare calculation engine (pure business logic)
├── utils/
│   └── csrf.py                # CSRF token helpers
├── templates/
│   ├── base.html              # Shared layout (navbar, footer)
│   ├── index.html             # Calculator homepage
│   ├── _flashes.html          # Flash message partial
│   ├── error.html             # Error page template
│   └── partials/
│       └── calculator.html    # Calculator form, modals, map card
├── static/
│   ├── favicon.svg
│   ├── css/style.css
│   ├── js/
│   │   ├── calculator.js      # Calculator form logic + modals
│   │   ├── main.js            # Site-wide helpers (alerts, auto-dismiss)
│   │   └── map.js             # Leaflet map, geocoding, route display
│   └── vendor/bootstrap/      # Bootstrap 5 (vendored)
└── tests/
    ├── test_fare_calculator.py # Pure fare-engine unit tests (no DB)
    └── test_routes.py          # Flask client integration tests (needs MySQL)
```

## Setup (Windows PowerShell)

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

Open `.env` and set your MySQL credentials, change `SECRET_KEY` to a random
string, and set `SESSION_COOKIE_SECURE=true` when behind HTTPS.

### 3. Create the database, tables, and sample data

```powershell
python database\setup_db.py
```

Safe to re-run. Creates the `farecal_db` database, all tables, sample transport
and passenger types, sample fare rates, and common routes.

### 4. (Optional) Load official LTFRB rates

```powershell
python database\load_official_rates.py
```

Overwrites sample rates with the current published LTFRB fare structures.

### 5. Run the application

```powershell
python app.py
```

Open http://127.0.0.1:5000 in your browser.

## Running the tests

```powershell
$env:PYTHONPATH = "C:\Users\Vin\OneDrive\Desktop\FareCal"

# Fare engine tests (no database required)
python -m unittest tests.test_fare_calculator

# Integration tests (needs a running MySQL with farecal_db seeded)
python -m unittest tests.test_routes

# Full suite
python -m unittest discover -s tests
```

## Configuration (.env)

| Variable              | Default     | Description                                             |
|-----------------------|-------------|---------------------------------------------------------|
| `SECRET_KEY`          | (none)      | Flask session secret — **must be set in production**    |
| `SESSION_COOKIE_SECURE` | `false`   | Set to `true` behind HTTPS (Render/Railway/PythonAnywhere) |
| `DB_HOST`             | `localhost` | MySQL host                                              |
| `DB_PORT`             | `3306`      | MySQL port                                              |
| `DB_NAME`             | `farecal_db`| Database name                                           |
| `DB_USER`             | `root`      | MySQL user                                              |
| `DB_PASSWORD`         | (none)      | MySQL password                                          |
| `MAX_DISTANCE_KM`     | `500`       | Max distance the calculator accepts                     |

## Deployment

FareCal deploys as two services: a **MySQL database** (on Railway) and a
**web service** (on Render, Railway, or PythonAnywhere).

### Railway — MySQL database

1. Create a new Railway project → add a **MySQL** plugin.
2. In the MySQL plugin's **Data** tab, copy the connection values:
   Host, Port, Username, Password, and Database name.
3. Seed the database by running `setup_db.py` locally with those values
   in your `.env`, or from the Railway shell:
   ```
   python database/setup_db.py
   ```

### Render — Web service

1. Connect your GitHub repo (`benrehhhh/FareCal`) to Render.
2. **Build command:** `pip install -r requirements.txt`
3. **Start command:** `gunicorn wsgi:app`
4. **Health check path:** `/healthz`
5. Add environment variables (from your Railway MySQL credentials):
   ```
   SECRET_KEY=<random-strong-string>
   SESSION_COOKIE_SECURE=true
   DB_HOST=<railway-mysql-host>
   DB_PORT=<railway-mysql-port>
   DB_NAME=farecal_db
   DB_USER=<railway-mysql-user>
   DB_PASSWORD=<railway-mysql-password>
   MAX_DISTANCE_KM=500
   ```
6. Deploy. The app connects to Railway's MySQL over the internet.

### PythonAnywhere

1. Upload or `git clone` the repo into your home directory.
2. Create a virtualenv and `pip install -r requirements.txt`.
3. Set the same `DB_*` / `SECRET_KEY` env vars in the Web tab.
4. In the WSGI configuration file, replace the default with:
   ```python
   import sys
   project_home = '/home/<your-username>/FareCal'
   if project_home not in sys.path:
       sys.path.insert(0, project_home)
   from app import app as application
   ```
5. Seed the database once via the Bash console:
   ```
   cd ~/FareCal && python database/setup_db.py
   ```

### External services

The calculator uses free public APIs at runtime — no API keys required:

- **Nominatim** (OpenStreetMap) for place search / geocoding
- **OSRM** for route distance and duration
- **Leaflet + OSM tiles** for the map display

All requests originate from the user's browser, not the server.

## Development notes

- Fare rates are entirely database-driven — nothing is hard-coded in the
  frontend. Different transport types can use different fare structures
  (`base_succeeding` or `per_km`) via the `fare_method` column.
- The database is created by `database/setup_db.py` — you never need to run
  raw SQL.
- CSRF protection is enforced on all HTML form POSTs. API endpoints
  (`/api/*`) are exempt.
- A `GET /healthz` endpoint returns `200` with DB status, useful for
  platform health checks.