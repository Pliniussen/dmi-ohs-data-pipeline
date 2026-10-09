# DMI OHS Pipeline Summary

## Extraction flow

1. Fetch current observations from the DMI observation API for the configured station.
2. Extract the observation fields from each API feature.
3. Look up each `parameterId` in `reference_data/dmi-parameter-catalog.json`.
4. Load the static parameter metadata and observations into PostgreSQL.
5. Report an error for any observed parameter missing from the catalog.

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

- `reference_data/dmi-parameter-catalog.json` contains the static parameter metadata and code mappings.
- `sample_data/odense-observations-2026-10-07.json` contains a saved observation sample for the configured station.
- The raw API files are strict JSON; extraction commands are kept in separate `.command.txt` files.

Source documentation:  
https://www.dmi.dk/friedata/dokumentation/meteorological-observations-data  
https://www.dmi.dk/friedata/dokumentation/meteorological-observation-api

## Current implementation status

Completed:

- PostgreSQL and Docker Compose development environment.
- Station coordinate schema based on observation API data.
- Parameter metadata schema based on the local DMI catalog.
- Observation schema with parameter references and duplicate protection.
- Schema bootstrap wiring through PostgreSQL's initialization directory.
- Basic database connection integration test and calculator unit tests.

Not yet completed:

- DMI API extraction.
- JSON validation and transformation.
- Catalog validation for every observed parameter.
- Loading parameters and observations into PostgreSQL.
- Idempotent upserts and transaction handling in the ETL loader.
- Indoor hardware source/device model.

## Known issues, ordered by priority

### P0 — Main project functionality is missing

1. **The ETL pipeline is not implemented.** The application currently
   connects to PostgreSQL but does not fetch DMI data, transform JSON, or load
   records.
2. **The database is not populated.** The schema exists, but no parameters or
   observations are loaded automatically.
3. **There is no complete pipeline result or error workflow.** The application
   does not report extracted record counts, load results, or meaningful
   failures.

### P1 — Correctness and reliability

4. **Idempotent loading is not implemented.** Database uniqueness constraints
   exist, but the loader still needs deliberate upsert behavior so repeated
   runs do not fail or create duplicates.
5. **API and input validation are missing.** The project needs handling for
   HTTP failures, timeouts, malformed JSON, missing fields, empty responses,
   invalid timestamps, and unexpected value types.
6. **Unknown catalog parameters are not handled in code.** The loader must
   stop and report an error when an observation parameter is missing from
   `reference_data/dmi-parameter-catalog.json`.
7. **Transaction and rollback behavior is not implemented.** A failed load
   should not leave parameters and observations partially inserted.
8. **The required 95% test coverage is not met or enforced.** ETL behavior,
   validation, database writes, and failure paths still need tests, and the
   test command does not currently enforce a minimum coverage threshold.
9. **The integration test requires a configured PostgreSQL environment.**
    Running pytest directly outside the Compose test container fails unless
    the PostgreSQL environment variables and database are available.

### P2 — Maintainability and delivery

11. **There is no documented ETL command yet.** The README needs a command
    explaining how to load the saved fixtures or fetch fresh DMI data.
11. **There are no schema or loader integration tests.** The project needs
   tests for schema creation, upserts, duplicate handling, catalog
   validation, and observation loading.
13. **Generated and temporary data files are not clearly separated.** The
    contents of `data/` should distinguish authoritative fixtures, downloaded
    raw responses, extraction commands, and temporary files.
14. **The application image currently copies the database directory but not
    the data fixtures.** The future loader must either copy/mount the fixture
    data or accept explicit input paths.
15. **No continuous integration workflow is configured.** Tests, coverage,
    Compose validation, and other checks are not run automatically on pushes.

### P3 — Later extensibility

15. **Indoor hardware sources are not modeled yet.** When sensors are
   introduced, add a source or device identifier to observations.

## Recommended next steps

1. Implement extraction and transformation functions for the saved observation
   JSON fixture.
2. Implement a PostgreSQL loader for parameters and observations with
   validation, transactions, and `ON CONFLICT` upserts.
3. Add focused unit tests for transformation and error cases.
4. Add database integration tests for the complete load and repeat-load
   behavior.
5. Enforce the 95% coverage requirement.
6. Document and run the complete ETL command.
7. Add the indoor source/device model when the building hardware is
   available.
