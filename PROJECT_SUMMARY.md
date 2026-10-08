# DMI OHS Pipeline Summary

## Extraction flow

1. Discover or select a DMI `stationId`.
2. Fetch observations from the DMI observation API using the station ID and time range.
3. Fetch station metadata from the DMI station API using the same station ID.
4. Extract distinct `parameterId` values from the observation response.
5. Look up those IDs in `data/dmi-parameter-catalog.json`.
6. Load station metadata, parameter metadata, code mappings, and observations into PostgreSQL.
7. Report an error for any observed parameter missing from the catalog instead of inserting incomplete metadata.

The parameter catalog is local reference data derived from DMI documentation. It supplies metadata not included in the observation API, including units, frequencies, descriptions, and coded-value descriptions. All catalog descriptions use arrays of paragraphs so the loader can consistently use `"\n\n".join(description)`.

## Database schema

### `stations`

Stores the current station metadata from the station API. The DMI `stationId`
identifies one station row. The API may return multiple historical records for
one station, so the loader selects the current record, while retaining its
validity fields and raw API payload for traceability.

Important fields: `station_id`, `name`, `latitude`, `longitude`, `country`,
`type`, `status`, `operation_from`, `operation_to`, `valid_from`, `valid_to`,
`last_seen_at`, and the raw API feature ID.

### `parameters`

Stores the catalog metadata keyed by `parameter_id`.

Important fields: `parameter_id` (primary key), `unit`, `frequency`, and `description`.

### `parameter_codes`

Stores documented coded values separately from parameter metadata.

Important fields: `parameter_id`, `code`, and `description`, with a primary key on `(parameter_id, code)`. This includes values such as precipitation `-0.1`, snow depth `-1`, cloud-cover codes, wind-direction code `0`, and weather codes.

### `observations`

Uses long format: one row per station, parameter, observation timestamp, and value.

Important fields: source observation ID, `station_id`, `parameter_id`, `observed_at`, `created_at`, numeric `value`, and coordinates if they are retained from the observation feature. Add a uniqueness constraint on the source observation ID, or on the natural key if the API does not provide a stable ID.

## Relationships

```text
stations 1 ---- * observations * ---- 1 parameters
parameters 1 ---- * parameter_codes
```

The first version intentionally models current station metadata only. This
keeps comparisons focused on current outdoor conditions. When indoor
measurement hardware is added, a generalized source/device table can be
introduced so DMI stations and indoor sensors can both provide observations.

The database structure is fixed. New stations, parameters, codes, and observations are inserted or upserted as rows; the schema is not changed dynamically.

The current schema is implemented in `database/schema.sql`. It is mounted into
PostgreSQL as the bootstrap schema for a new database volume. The application
also includes a migration runner in `dmi_ohs/migrations.py`, which looks for
numbered SQL files in `database/migrations` and records applied migrations in
the `schema_migrations` table. There are currently no migration files because
the project has been reset to the current schema and no older schema is in
use. Future schema changes should be added as new numbered migration files.

## Current reference data

- `data/dmi-parameter-catalog.json` contains the DMI-documented parameter metadata and code mappings.
- `data/odense-observations-2026-10-07.json` contains a saved observation sample for station `06120`.
- `data/odense-station.json` contains saved station metadata for station `06120`.
- The raw API files are strict JSON; extraction commands are kept in separate `.command.txt` files.

Source documentation:  
https://www.dmi.dk/friedata/dokumentation/meteorological-observations-data  
https://www.dmi.dk/friedata/dokumentation/meteorological-observation-api

## Current implementation status

Completed:

- PostgreSQL and Docker Compose development environment.
- Current-state DMI station schema.
- Parameter and coded-value schema based on the local DMI catalog.
- Long-format observation schema with foreign keys and duplicate protection.
- Schema bootstrap wiring through PostgreSQL's initialization directory.
- Migration runner for future numbered schema migrations.
- Basic database connection integration test and calculator unit tests.

Not yet completed:

- DMI API extraction.
- JSON validation and transformation.
- Catalog validation for every observed parameter.
- Loading stations, parameters, codes, and observations into PostgreSQL.
- Idempotent upserts and transaction handling in the ETL loader.
- Indoor hardware source/device model.

## Known issues, ordered by priority

### P0 — Main project functionality is missing

1. **The ETL pipeline is not implemented.** The application currently
   connects to PostgreSQL but does not fetch DMI data, transform JSON, or load
   records.
2. **The database is not populated.** The schema exists, but no stations,
   parameters, parameter codes, or observations are loaded automatically.
3. **There is no complete pipeline result or error workflow.** The application
   does not report extracted record counts, load results, or meaningful
   failures.

### P1 — Correctness and reliability

4. **The loader must select the current DMI station record.** The station API
   can return multiple records for one `stationId`; the ETL process must choose
   the record appropriate for the current time.
5. **Idempotent loading is not implemented.** Database uniqueness constraints
   exist, but the loader still needs deliberate upsert behavior so repeated
   runs do not fail or create duplicates.
6. **API and input validation are missing.** The project needs handling for
   HTTP failures, timeouts, malformed JSON, missing fields, empty responses,
   invalid timestamps, and unexpected value types.
7. **Unknown catalog parameters are not handled in code.** The loader must
   stop and report an error when an observation parameter is missing from
   `dmi-parameter-catalog.json`.
8. **Transaction and rollback behavior is not implemented.** A failed load
   should not leave stations, parameters, and observations partially inserted.
9. **The required 95% test coverage is not met or enforced.** ETL behavior,
   validation, database writes, and failure paths still need tests, and the
   test command does not currently enforce a minimum coverage threshold.
10. **The integration test requires a configured PostgreSQL environment.**
    Running pytest directly outside the Compose test container fails unless
    the PostgreSQL environment variables and database are available.

### P2 — Maintainability and delivery

11. **There is no documented ETL command yet.** The README needs a command
    explaining how to load the saved fixtures or fetch fresh DMI data.
12. **There are no schema or loader integration tests.** The project needs
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

16. **Indoor hardware sources are not modeled yet.** When sensors are
    introduced, add a generalized source/device model so indoor sensors and
    DMI stations can be compared through the same observation structure.
17. **Station metadata history is intentionally not retained.** This is an
    accepted simplification because the current project focuses on present
    environmental conditions. Revisit it only if historical station changes
    become relevant.

## Recommended next steps

1. Implement extraction and transformation functions for the saved DMI JSON
   fixtures.
2. Implement a PostgreSQL loader with validation, transactions, and
   `ON CONFLICT` upserts.
3. Add focused unit tests for transformation and error cases.
4. Add database integration tests for the complete load and repeat-load
   behavior.
5. Enforce the 95% coverage requirement.
6. Document and run the complete ETL command.
7. Add the indoor source/device model when the building hardware is
   available.
