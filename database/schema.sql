-- ===================================================================
-- FareCal database schema + sample seed data
-- Run via: python database\setup_db.py   (safe to re-run)
-- ===================================================================

CREATE DATABASE IF NOT EXISTS farecal_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE farecal_db;

-- -------------------------------------------------------------------
-- users
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            INT UNSIGNED     NOT NULL AUTO_INCREMENT,
    name          VARCHAR(100)     NOT NULL,
    email         VARCHAR(150)     NOT NULL,
    password_hash VARCHAR(255)     NOT NULL,
    role          ENUM('user', 'admin') NOT NULL DEFAULT 'user',
    status        ENUM('active', 'inactive') NOT NULL DEFAULT 'active',
    created_at    DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_email (email)
) ENGINE = InnoDB;

-- -------------------------------------------------------------------
-- transport_types
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transport_types (
    id          INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    name        VARCHAR(100)  NOT NULL,
    description VARCHAR(255)  NULL,
    status      ENUM('active', 'inactive') NOT NULL DEFAULT 'active',
    created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                              ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_transport_types_name (name)
) ENGINE = InnoDB;

-- -------------------------------------------------------------------
-- fare_rates
-- A transport type can have different fare rules configured here.
-- `fare_method` selects HOW the fare engine calculates:
--   'base_succeeding' -> base_fare up to base_distance, then
--                        succeeding_rate per km beyond that
--   'per_km'          -> per_km_rate * distance (with optional minimum)
-- Not every column is used by every method.
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fare_rates (
    id                INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    transport_type_id INT UNSIGNED  NOT NULL,
    fare_method       ENUM('base_succeeding', 'per_km') NOT NULL DEFAULT 'base_succeeding',
    base_distance     DECIMAL(10, 2) NULL,
    base_fare         DECIMAL(10, 2) NULL,
    succeeding_rate   DECIMAL(10, 4) NULL,   -- per km beyond base_distance
    per_km_rate       DECIMAL(10, 4) NULL,   -- used by the 'per_km' method
    minimum_fare      DECIMAL(10, 2) NULL,
    maximum_fare      DECIMAL(10, 2) NULL,
    rounding_rule     VARCHAR(30)  NOT NULL DEFAULT 'round_nearest_025',
    effective_date    DATE         NOT NULL,
    expiration_date   DATE         NULL,
    status            ENUM('active', 'inactive') NOT NULL DEFAULT 'active',
    source_reference  VARCHAR(255) NULL,     -- e.g. "SAMPLE test data", LTFRB Memo...
    created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_fare_rates_type_date (transport_type_id, effective_date),
    CONSTRAINT fk_fare_rates_transport_type
        FOREIGN KEY (transport_type_id) REFERENCES transport_types (id)
        ON DELETE CASCADE
) ENGINE = InnoDB;

-- -------------------------------------------------------------------
-- passenger_types
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS passenger_types (
    id                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
    name                VARCHAR(100) NOT NULL,
    discount_percentage DECIMAL(5, 2) NOT NULL DEFAULT 0,
    description         VARCHAR(255) NULL,
    status              ENUM('active', 'inactive') NOT NULL DEFAULT 'active',
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                     ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_passenger_types_name (name)
) ENGINE = InnoDB;

-- -------------------------------------------------------------------
-- fare_calculations  (calculation history)
-- user_id is nullable so guests can calculate without an account.
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fare_calculations (
    id                   INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id              INT UNSIGNED NULL,
    transport_type_id    INT UNSIGNED NOT NULL,
    passenger_type_id    INT UNSIGNED NOT NULL,
    distance             DECIMAL(10, 2) NOT NULL,
    regular_fare         DECIMAL(10, 2) NOT NULL,
    discount_percentage  DECIMAL(5, 2) NOT NULL DEFAULT 0,
    discount_amount      DECIMAL(10, 2) NOT NULL DEFAULT 0,
    final_fare           DECIMAL(10, 2) NOT NULL,
    calculated_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_fare_calculations_user (user_id),
    KEY idx_fare_calculations_date (calculated_at),
    CONSTRAINT fk_fare_calculations_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE SET NULL,
    CONSTRAINT fk_fare_calculations_transport_type
        FOREIGN KEY (transport_type_id) REFERENCES transport_types (id),
    CONSTRAINT fk_fare_calculations_passenger_type
        FOREIGN KEY (passenger_type_id) REFERENCES passenger_types (id)
) ENGINE = InnoDB;

-- -------------------------------------------------------------------
-- routes  (common-route presets so users can skip typing a distance)
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS routes (
    id                INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    transport_type_id INT UNSIGNED  NOT NULL,
    origin            VARCHAR(100)  NOT NULL,
    destination       VARCHAR(100)  NOT NULL,
    distance_km       DECIMAL(10, 2) NOT NULL,
    status            ENUM('active', 'inactive') NOT NULL DEFAULT 'active',
    created_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_routes_transport_origin_destination
        (transport_type_id, origin, destination),
    CONSTRAINT fk_routes_transport_type
        FOREIGN KEY (transport_type_id) REFERENCES transport_types (id)
        ON DELETE CASCADE
) ENGINE = InnoDB;

-- ===================================================================
-- SAMPLE SEED DATA
-- These values are TEST data, not official fare rates.
-- source_reference marks every row as 'SAMPLE test data'.
-- ===================================================================

-- Transport types ---------------------------------------------------
INSERT IGNORE INTO transport_types (name, description) VALUES
    ('Traditional PUJ', 'Traditional jeepney operating under the old franchise system.'),
    ('Modernized PUJ', 'Modernized or "class 2" jeepney operating under the public utility vehicle modernization program.'),
    ('UV Express', 'Utility vehicle operating on a fixed route, seat-limited.'),
    ('Bus', 'City or provincial bus service.'),
    ('Taxi', 'Metered taxi service.');

-- Passenger types ---------------------------------------------------
INSERT IGNORE INTO passenger_types (name, discount_percentage, description) VALUES
    ('Regular Passenger', 0.00, 'Full-paying passenger. No discount applies.'),
    ('Student', 20.00, '20% discount as provided for eligible student passengers.'),
    ('Senior Citizen', 20.00, '20% discount for senior citizens.'),
    ('Person with Disability (PWD)', 20.00, '20% discount for persons with disability.');

-- Sample fare rates -------------------------------------------------
-- NOTE: These are clearly-marked SAMPLE amounts used for development and
-- demonstration only. They are NOT official Philippine fare rates.
INSERT IGNORE INTO fare_rates
    (transport_type_id, fare_method, base_distance, base_fare,
     succeeding_rate, per_km_rate, minimum_fare, maximum_fare,
     rounding_rule, effective_date, expiration_date, status, source_reference)
SELECT id, 'base_succeeding', 4.00, 13.00, 1.80, NULL, NULL, NULL,
       'round_up_025', '2025-01-01', NULL, 'active',
       'SAMPLE test data - not official'
FROM transport_types WHERE name = 'Traditional PUJ';

INSERT IGNORE INTO fare_rates
    (transport_type_id, fare_method, base_distance, base_fare,
     succeeding_rate, per_km_rate, minimum_fare, maximum_fare,
     rounding_rule, effective_date, expiration_date, status, source_reference)
SELECT id, 'base_succeeding', 4.00, 13.00, 2.00, NULL, NULL, NULL,
       'round_up_025', '2025-01-01', NULL, 'active',
       'SAMPLE test data - not official'
FROM transport_types WHERE name = 'Modernized PUJ';

INSERT IGNORE INTO fare_rates
    (transport_type_id, fare_method, base_distance, base_fare,
     succeeding_rate, per_km_rate, minimum_fare, maximum_fare,
     rounding_rule, effective_date, expiration_date, status, source_reference)
SELECT id, 'per_km', NULL, NULL, NULL, 11.50, 55.00, NULL,
       'round_up_1', '2025-01-01', NULL, 'active',
       'SAMPLE test data - not official'
FROM transport_types WHERE name = 'UV Express';

INSERT IGNORE INTO fare_rates
    (transport_type_id, fare_method, base_distance, base_fare,
     succeeding_rate, per_km_rate, minimum_fare, maximum_fare,
     rounding_rule, effective_date, expiration_date, status, source_reference)
SELECT id, 'base_succeeding', 5.00, 15.00, 3.00, NULL, NULL, NULL,
       'round_up_1', '2025-01-01', NULL, 'active',
       'SAMPLE test data - not official'
FROM transport_types WHERE name = 'Bus';

INSERT IGNORE INTO fare_rates
    (transport_type_id, fare_method, base_distance, base_fare,
     succeeding_rate, per_km_rate, minimum_fare, maximum_fare,
     rounding_rule, effective_date, expiration_date, status, source_reference)
SELECT id, 'base_succeeding', 1.00, 55.00, 14.00, NULL, NULL, NULL,
       'round_up_1', '2025-01-01', NULL, 'active',
       'SAMPLE test data - not official'
FROM transport_types WHERE name = 'Taxi';

-- -------------------------------------------------------------------
-- Sample common routes
-- Distance values are APPROXIMATE community/public estimates (regular
-- point-to-point distance), intended for quick fare estimation only.
-- -------------------------------------------------------------------
INSERT IGNORE INTO routes
    (transport_type_id, origin, destination, distance_km)
SELECT id, 'Divisoria', 'Quiapo', 3.00
FROM transport_types WHERE name = 'Traditional PUJ';

INSERT IGNORE INTO routes
    (transport_type_id, origin, destination, distance_km)
SELECT id, 'Monumento', 'Cubao', 12.50
FROM transport_types WHERE name = 'Traditional PUJ';

INSERT IGNORE INTO routes
    (transport_type_id, origin, destination, distance_km)
SELECT id, 'Baclaran', 'Bacoor', 13.50
FROM transport_types WHERE name = 'Traditional PUJ';

INSERT IGNORE INTO routes
    (transport_type_id, origin, destination, distance_km)
SELECT id, 'SM City Fairview', 'Cubao', 18.00
FROM transport_types WHERE name = 'Modernized PUJ';

INSERT IGNORE INTO routes
    (transport_type_id, origin, destination, distance_km)
SELECT id, 'Alabang', 'Baclaran', 18.50
FROM transport_types WHERE name = 'Modernized PUJ';

INSERT IGNORE INTO routes
    (transport_type_id, origin, destination, distance_km)
SELECT id, 'Binangonan', 'SM Megamall', 25.00
FROM transport_types WHERE name = 'UV Express';

INSERT IGNORE INTO routes
    (transport_type_id, origin, destination, distance_km)
SELECT id, 'Alabang', 'Ayala', 14.50
FROM transport_types WHERE name = 'UV Express';

INSERT IGNORE INTO routes
    (transport_type_id, origin, destination, distance_km)
SELECT id, 'Pacita Complex', 'Ayala', 15.50
FROM transport_types WHERE name = 'Bus';

INSERT IGNORE INTO routes
    (transport_type_id, origin, destination, distance_km)
SELECT id, 'Monumento', 'Pasay', 14.00
FROM transport_types WHERE name = 'Bus';

INSERT IGNORE INTO routes
    (transport_type_id, origin, destination, distance_km)
SELECT id, 'SM City Fairview', 'Monumento', 15.50
FROM transport_types WHERE name = 'Bus';

INSERT IGNORE INTO routes
    (transport_type_id, origin, destination, distance_km)
SELECT id, 'NAIA Terminal 3', 'Makati (Ayala)', 7.50
FROM transport_types WHERE name = 'Taxi';

INSERT IGNORE INTO routes
    (transport_type_id, origin, destination, distance_km)
SELECT id, 'NAIA Terminal 3', 'Divisoria', 12.00
FROM transport_types WHERE name = 'Taxi';