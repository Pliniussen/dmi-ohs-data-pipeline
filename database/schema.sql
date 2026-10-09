-- DMI OHS database schema
--
-- This file is executed automatically by the official PostgreSQL Docker image
-- when the database volume is created for the first time.

CREATE TABLE IF NOT EXISTS stations (
    station_id TEXT PRIMARY KEY,
    longitude NUMERIC(8, 5) NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    latitude NUMERIC(8, 5) NOT NULL CHECK (latitude BETWEEN -90 AND 90)
);

COMMENT ON TABLE stations IS
    'Station identifiers and coordinates extracted from observation features.';

CREATE TABLE IF NOT EXISTS parameters (
    parameter_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    unit TEXT NOT NULL,
    frequency TEXT NOT NULL
);

COMMENT ON TABLE parameters IS
    'Static metadata from the local DMI parameter catalog.';

CREATE TABLE IF NOT EXISTS parameter_value_codes (
    parameter_id TEXT NOT NULL REFERENCES parameters (parameter_id),
    code NUMERIC NOT NULL,
    description TEXT NOT NULL,
    PRIMARY KEY (parameter_id, code)
);

COMMENT ON TABLE parameter_value_codes IS
    'Static descriptions for parameter-specific coded values.';

CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    station_id TEXT NOT NULL REFERENCES stations (station_id),
    parameter_id TEXT NOT NULL REFERENCES parameters (parameter_id),
    observed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    value NUMERIC
);

COMMENT ON TABLE observations IS
    'Current observations returned by the DMI observation API.';

CREATE INDEX IF NOT EXISTS observations_station_time_idx
    ON observations (station_id, observed_at);

CREATE INDEX IF NOT EXISTS observations_parameter_time_idx
    ON observations (parameter_id, observed_at);
