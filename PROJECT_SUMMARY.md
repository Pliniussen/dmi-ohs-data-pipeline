# DMI OHS Pipeline Summary

## Extraction flow

1. Read the saved observation JSON for the configured station. The pipeline does not yet fetch from the API.
2. Validate and normalize its features into station and observation records.
3. Check every observed `parameterId` against `reference_data/dmi-parameter-catalog.json`.
4. Upsert parameter metadata, value-code descriptions, stations, and observations into PostgreSQL in one transaction.
5. Print the number of rows loaded for each table.

The parameter catalog is local reference data derived from DMI documentation. It supplies the static unit, frequency, and coded-value descriptions not included in the observation API.

## Database schema

### `stations`

Stores the station ID and coordinates extracted from observation API features.
The first version uses one configured station, but keeping the station ID in a
separate table prevents coordinates from being repeated on every observation.

Important fields: `station_id` (primary key), `longitude`, and `latitude`.

### `parameters`

Stores the static catalog metadata keyed by `parameter_id`.

Important fields: `parameter_id` (primary key), `description`, `unit`,
and `frequency`.

### `parameter_value_codes`

Stores static descriptions for numeric values that have a documented meaning
for a specific parameter, such as weather codes or traces of precipitation.

Important fields: `parameter_id`, `code`, and `description`, with a composite
primary key on `(parameter_id, code)`.

### `observations`

Stores the current observations returned by the observation API. The station
ID remains on each row because it is part of the API response, even though the
first version uses only one configured station.

Important fields: API feature `id`, `station_id`, `parameter_id`, `observed_at`,
`created_at`, and `value`.

## Relationships

```text
stations 1 ---- * observations * ---- 1 parameters
parameters 1 ---- * parameter_value_codes
```

The first version intentionally models only current outdoor observations from
one configured DMI station. When indoor measurement hardware is added, the
observation model can be extended with a source or device identifier.

The database structure is fixed. Parameter metadata, value-code descriptions,
and observations are inserted or upserted as rows; the schema is not changed
dynamically. Value descriptions can be resolved by joining
`observations.parameter_id` and `observations.value` to
`parameter_value_codes.parameter_id` and `parameter_value_codes.code`.

The current schema is implemented in `database/schema.sql`. It is mounted into
PostgreSQL as the bootstrap schema for a new database volume. During this
early development phase, schema changes are applied by deleting the database
volume and creating it again.

## Current reference data

- `reference_data/dmi-parameter-catalog.json` contains static parameter metadata and code mappings.
- `sample_data/odense-observations-2026-10-07.json` contains a saved observation sample for the configured station.
- The raw API files are strict JSON; extraction commands are kept in separate `.command.txt` files.

Source documentation:  
https://www.dmi.dk/friedata/dokumentation/meteorological-observations-data  
https://www.dmi.dk/friedata/dokumentation/meteorological-observation-api

## Current implementation status

Completed:

- PostgreSQL and Docker Compose development environment.
- Station, parameter, value-code, and observation tables with foreign keys and duplicate protection.
- Schema bootstrap wiring through PostgreSQL's initialization directory.
- JSON parsing and validation for observation features, station coordinates, timestamps, and values.
- Validation of observed parameter IDs against the local catalog.
- Transactional, idempotent upserts for catalog data, stations, and observations.
- A command-line pipeline that loads the bundled sample by default or accepts a JSON path, then reports row counts.
- Unit tests for parsing, validation, and shared catalog code sets, plus PostgreSQL integration tests for loading, repeat loads, rollback, and the main command.

Not yet completed:

- Fetching current observations directly from the DMI API.
- Indoor hardware source/device model.

## Known limitations

- The pipeline currently consumes saved JSON; it does not make API requests or handle API-specific retries and timeouts.
- Catalog entries are upserted when present, but entries removed from the local catalog are not deleted from PostgreSQL.
- Coverage is collected by the Compose test command, but a 95% minimum is not enforced.
- There is no continuous integration workflow yet.
- The schema file bootstraps new database volumes only. Existing volumes will need migrations when the schema evolves.

## Recommended next steps

1. Add DMI API extraction with suitable timeout and retry behavior.
2. Decide whether catalog synchronization should remove database entries that are no longer in the local catalog.
3. Enforce the 95% coverage target if it remains a project requirement, and add continuous integration.
4. Add the indoor source/device model when the building hardware is available.
