# DMI OHS Pipeline Summary

## Extraction flow

1. Read a saved observation JSON file (the bundled Odense sample by default, or a path supplied on the command line). The pipeline does not yet fetch from the API.
2. Validate and normalize its features into station and observation records.
3. Check every observed `parameterId` against `reference_data/dmi-parameter-catalog.json`.
4. Upsert parameter metadata, value-code descriptions, stations, and observations into PostgreSQL in one transaction.
5. Print the number of input rows submitted to each table's upsert statements. These are not counts of rows newly inserted or changed.

The parameter catalog is local reference data derived from DMI documentation. It supplies the static unit, frequency, and coded-value descriptions not included in the observation API.

## Database schema

### `stations`

Stores the station ID and coordinates extracted from observation API features.
The bundled sample currently contains one station, while the parser supports
multiple stations. Keeping the station ID in a separate table prevents
coordinates from being repeated on every observation.

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
bundled sample currently includes only one station.

Important fields: API feature `id`, `station_id`, `parameter_id`, `observed_at`,
`created_at`, and `value`.

## Relationships

```text
stations 1 ---- * observations * ---- 1 parameters
parameters 1 ---- * parameter_value_codes
```

The current sample contains outdoor observations from one DMI station. The
pipeline can also load additional stations present in an input file, but does
not call the DMI station API. When indoor measurement hardware is added, the
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
- `sample_data/odense-observations-2026-10-07.json` contains saved observations for Odense station `06120`.
- The saved API responses are strict JSON. The `.command.txt` curl examples currently write to a legacy `data/` directory; adjust the output path if rerunning them, since the project fixtures are stored in `sample_data/`.

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
- A command-line pipeline that loads the bundled sample by default or accepts a JSON path, then reports input row counts submitted to the upserts.
- Unit tests for parsing, input validation, and catalog parameter validation, plus PostgreSQL integration tests for connectivity, loading, repeat loads, rollback, and the `run()` entry point.

Not yet completed:

- Fetching current observations directly from the DMI API.
- Indoor hardware source/device model.

## Running the services and protecting database data

### What the Docker and PostgreSQL names mean

- **Docker Compose** reads `docker-compose.yml` and starts the containers described there. The project has an `app` service for the pipeline, a `tests` service for pytest, a `db` service running PostgreSQL, and a `pgadmin` service for the database browser.
- **PostgreSQL** is the database server software. The Compose service is named `db`; containers on the Compose network use that name to reach the server.
- **`POSTGRES_HOST`** is the server address. In this project, `.env.example` sets it to `db`. **`POSTGRES_DB`** is the name of one database inside that server; `.env.example` sets it to `postgres_db`. `POSTGRES_PORT` is the server port, normally `5432`.
- The app and tests read these environment variables in `dmi_ohs/database.py`. `docker-compose.yml` passes the values into each container. `${POSTGRES_DB}` means “use the value supplied by the environment or `.env` file.”
- **`postgres_data`** is a Docker-managed persistent volume mounted at PostgreSQL's data directory. PostgreSQL stores its internal files there for all databases on that server. It is storage used by the server, not a database to connect to or a directory to edit by hand.
- **pgAdmin** is a separate web interface that connects to PostgreSQL. It helps browse databases and run queries; it does not store the pipeline's database records. It is available at `http://localhost:8080` while its service is running.

The `app` service uses the default command from `Dockerfile`, `python -m dmi_ohs.main`: it loads the bundled sample into the database and then exits. To start the database, pgAdmin, and run that app without starting tests, use `docker compose up --build db pgadmin app`. To start only PostgreSQL in the background, use `docker compose up -d db`.

### Why the integration tests can delete data

In `docker-compose.yml`, `app` and `tests` currently receive the same `POSTGRES_DB`. The `connection` fixture in `tests/integration/test_load.py` calls `clear()` before and after each test that uses it. `clear()` runs `TRUNCATE` on `observations`, `parameter_value_codes`, `parameters`, and `stations`. This deletes the rows in those tables in whichever database the test connection uses. Do not run these integration tests against a database containing data you need to keep.

### Recommended protection: a separate test database on the same server

This does not require another PostgreSQL container. Keep the app connected to the existing database and point only the `tests` service at a second database, for example `dmi_ohs_test`:

```yaml
app:
  environment:
    POSTGRES_DB: ${POSTGRES_DB}

tests:
  environment:
    POSTGRES_HOST: ${POSTGRES_HOST}
    POSTGRES_PORT: ${POSTGRES_PORT}
    POSTGRES_DB: ${TEST_POSTGRES_DB:-dmi_ohs_test}
    POSTGRES_USER: ${POSTGRES_USER}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
```

The snippet shows only the relevant settings; keep the other service settings already in `docker-compose.yml`. `TEST_POSTGRES_DB` is a database name, not a secret. It can be set in `.env` (`TEST_POSTGRES_DB=dmi_ohs_test`) or left to the fallback shown above.

The test database must have the project's tables too. `database/schema.sql` defines those tables. The `db` service mounts that file at `/docker-entrypoint-initdb.d/001-schema.sql`; the official PostgreSQL image runs scripts there only while initializing an empty data directory. It creates the initial database named by `POSTGRES_DB` and runs the schema file against it. A persistent, already-initialized `postgres_data` volume is not initialized again just because the Compose file or SQL changes.

For the existing volume, create the test database and apply the schema once. Start `db`, then run:

```sh
docker compose exec db sh -c 'createdb -U "$POSTGRES_USER" dmi_ohs_test'
docker compose exec -T db sh -c \
	'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d dmi_ohs_test' \
	< database/schema.sql
```

After setting the `tests` service to use `dmi_ohs_test`, run the suite with `docker compose run --build --rm tests`. The fixture's `TRUNCATE` will then clear test rows only; the app database remains separate. The setup commands above are one-time per persistent volume and assume `dmi_ohs_test` does not already exist. Do not use `docker compose down -v` as a shortcut: it deletes the persistent volumes, including `postgres_data` and all databases stored in it.

Applying `schema.sql` to two different databases is necessary: tables are part of each database and are not shared. Applying this project's current schema file again to the same database will not delete existing rows because its table and index definitions use `IF NOT EXISTS`, but it also will not update an existing table definition. Schema changes to an existing database should eventually use migrations.

## Known limitations

- The pipeline currently consumes saved JSON; it does not make API requests or handle API-specific retries and timeouts.
- PostgreSQL integration fixtures truncate their test tables. Until the tests are configured to use the separate `dmi_ohs_test` database described above, do not run them against app data that must be preserved.
- Catalog entries are upserted when present, but entries removed from the local catalog are not deleted from PostgreSQL.
- Coverage is collected by the Compose test command, but no minimum threshold is enforced.
- There is no continuous integration workflow yet.
- The schema file bootstraps new database volumes only. Existing volumes will need migrations when the schema evolves.

## Recommended next steps

1. Add DMI API extraction with suitable timeout and retry behavior.
2. Decide whether catalog synchronization should remove database entries that are no longer in the local catalog.
3. Enforce the 95% coverage target if it remains a project requirement, and add continuous integration.
4. Add the indoor source/device model when the building hardware is available.
