-- DMI OHS database schema
--
-- This file is executed automatically by the official PostgreSQL Docker image
-- when the database volume is created for the first time.

CREATE TABLE IF NOT EXISTS stations (
    station_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country CHAR(3),
    type TEXT,
    status TEXT,
    owner TEXT,
    region_id TEXT,
    wmo_country_code TEXT,
    wmo_station_id TEXT,
    latitude NUMERIC(8, 5) CHECK (latitude BETWEEN -90 AND 90),
    longitude NUMERIC(8, 5) CHECK (longitude BETWEEN -180 AND 180),
    operation_from TIMESTAMPTZ,
    operation_to TIMESTAMPTZ,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    raw_feature_id TEXT,
    raw_payload JSONB,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE stations IS
    'Current identity and metadata for each DMI station.';

CREATE TABLE IF NOT EXISTS parameters (
    parameter_id TEXT PRIMARY KEY,
    unit TEXT NOT NULL,
    frequency TEXT NOT NULL,
    description TEXT NOT NULL,
    catalog_source TEXT,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE parameters IS
    'DMI parameter definitions copied from the local catalog.';

CREATE TABLE IF NOT EXISTS parameter_codes (
    parameter_id TEXT NOT NULL REFERENCES parameters (parameter_id),
    code TEXT NOT NULL,
    description TEXT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (parameter_id, code)
);

COMMENT ON TABLE parameter_codes IS
    'Human-readable meanings for coded DMI values.';

CREATE TABLE IF NOT EXISTS observations (
    observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_observation_id TEXT NOT NULL UNIQUE,
    station_id TEXT NOT NULL REFERENCES stations (station_id),
    parameter_id TEXT NOT NULL REFERENCES parameters (parameter_id),
    observed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ,
    value NUMERIC,
    latitude NUMERIC(8, 5) CHECK (latitude BETWEEN -90 AND 90),
    longitude NUMERIC(8, 5) CHECK (longitude BETWEEN -180 AND 180),
    raw_payload JSONB NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE observations IS
    'Long-format measurements: one row per station, parameter, and time.';

CREATE INDEX IF NOT EXISTS observations_station_time_idx
    ON observations (station_id, observed_at);

CREATE INDEX IF NOT EXISTS observations_parameter_time_idx
    ON observations (parameter_id, observed_at);
