# DMI OHS Pipeline Summary

## Extraction flow

1. Fetch observations for each station in `DMI_STATION_IDS` (comma-separated, default `06120`) from the DMI observation API, or read a saved JSON file given with `--file`.
   - Each station gets its own fetch window. It starts one hour before that station's newest stored observation and ends now. A station with no stored observations (on the first run, or when it is newly added to the list) gets the last `DMI_INITIAL_LOOKBACK_HOURS` (default 24).
   - Each station is loaded in its own transaction. If one station fails, the others are still loaded, and the run then exits with an error naming the failed stations.
   - Pages are requested by offset until a page comes back short; the API's `next` link is present even on the last page, so it is not used to stop.
   - Requests time out and are retried with backoff on rate limits, server errors, and dropped connections.
2. Validate and normalize the features into station and observation records.
3. Skip observations whose `parameterId` is missing from `reference_data/dmi-parameter-catalog.json`, with a warning.
4. Upsert parameter metadata, value-code descriptions, stations, and observations into PostgreSQL in one transaction.
5. Print warnings, then the number of input rows submitted to each table's upsert statements. These are not counts of rows newly inserted or changed.

### Warnings

These situations are reported on stderr but do not stop the load:

- Observations with parameter IDs missing from the catalog are skipped.
- A station with coordinates that differ from those stored (or that differ within one input) is overwritten with the coordinates from its latest observation.
- If the same measurement (station, parameter, observed time) is stored under more than one observation ID, for example because DMI re-issued a corrected value, all rows are kept.

The parameter catalog is local reference data derived from DMI documentation. It supplies the static unit, frequency, and coded-value descriptions not included in the observation API.

### Design decisions

These were chosen deliberately when API extraction was added:

- **Incremental fetch window instead of a fixed period.** A missed run, or a pipeline that is down for days, is filled in on the next run, because the window always starts from the newest stored row. The one-hour overlap re-fetches rows that DMI publishes late; the upserts make the overlap harmless.
- **Skip unknown parameters instead of failing.** One new DMI parameter should not block all other data. Add the parameter to the catalog to start loading it.
- **Overwrite moved stations instead of failing.** A station move is unlikely in the near future. If it happens, the warning makes it visible and the newest coordinates are kept. Station history (DMI's `validFrom`/`validTo`) is not modelled.
- **Warn about duplicate measurements, don't prevent them.** It is not yet known whether DMI keeps the same observation ID when it corrects a value. If duplicates show up in practice, add a unique constraint on `(station_id, parameter_id, observed_at)` and change the observation upsert to target it. That is a schema change.
- **One transaction per station.** A station that fails (API error or bad data) does not roll back or block the others. The run still exits with an error, so a scheduler can notice.

### DMI API behaviour

Observed on `https://opendataapi.dmi.dk/v2/metObs/collections/observation/items`:

- No API key is required.
- Results are sorted newest first.
- The `datetime=start/end` range includes both ends; a 08:00–09:00 query returns rows observed at 08:00 and at 09:00.
- A `next` link is included even on the last, short page, so paging stops on page size instead (`limit=10000`, normally one page per run).
- Station coordinates are taken from the observation features. The station API (`.../collections/station/items`) is not called; `sample_data/odense-station.json` shows that station 06120 has had several coordinate periods since 1959.

## Configuration

Settings come from environment variables, which Compose reads from `.env`. `.env` is not committed; `.env.example` is its template, and both should contain the same keys so it is clear which settings are in effect. The code has defaults for the DMI settings, but they should still be written in `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `DMI_STATION_IDS` | `06120` | Comma-separated DMI station IDs to fetch, e.g. `06120,06180`. Kept as text because the leading zero is part of the ID. |
| `DMI_INITIAL_LOOKBACK_HOURS` | `24` | How far back to fetch for a station with no stored observations (first run, or newly added station). Ignored once the station has data. Set it higher (e.g. `720` for 30 days) before the first run to start with more history. |
| `TEST_POSTGRES_DB` | `dmi_ohs_test` | Database used by the tests. Must differ from `POSTGRES_DB`. |

To add a station, add its ID to `DMI_STATION_IDS` and run the pipeline; no code change is needed.

## Database schema

### `stations`

Stores the station ID and coordinates extracted from observation API features,
one row per station in `DMI_STATION_IDS`. Keeping the station ID in a separate
table prevents coordinates from being repeated on every observation.

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

Stores the current observations returned by the observation API. Each row
keeps its station ID, so observations from several stations share the table.

Important fields: API feature `id`, `station_id`, `parameter_id`, `observed_at`,
`created_at`, and `value`.

## Relationships

```text
stations 1 ---- * observations * ---- 1 parameters
parameters 1 ---- * parameter_value_codes
```

The pipeline loads outdoor observations from the DMI stations listed in
`DMI_STATION_IDS`. When indoor measurement hardware is added, the observation
model can be extended with a source or device identifier.

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
- The saved API responses are strict JSON. The `.command.txt` files contain the curl commands that produced them; run them from the project root to refresh the fixtures in `sample_data/`.

Source documentation:  
https://www.dmi.dk/friedata/dokumentation/meteorological-observations-data  
https://www.dmi.dk/friedata/dokumentation/meteorological-observation-api

## Current implementation status

Completed:

- PostgreSQL and Docker Compose development environment.
- Station, parameter, value-code, and observation tables with foreign keys and duplicate protection.
- Schema bootstrap wiring through PostgreSQL's initialization directory.
- JSON parsing and validation for observation features, station coordinates, timestamps, and values.
- Validation of the catalog's structure, and skipping (with a warning) of observations whose parameter is missing from it.
- Transactional, idempotent upserts for catalog data, stations, and observations, with warnings for moved stations and duplicate measurements.
- Incremental fetching from the DMI observation API with pagination, timeouts, and retries.
- A command-line pipeline that fetches from the API by default or loads a JSON file with `--file`, then reports input row counts submitted to the upserts.
- Unit tests for parsing, input and catalog validation, and the API client (using a fake HTTP session), plus PostgreSQL integration tests for connectivity, loading, repeat loads, rollback, warnings, and the incremental fetch window.

Not yet verified:

- The integration tests for the API, multi-station, warning, and incremental-window features have been written but not yet run against PostgreSQL. Run `pytest` in the rebuilt dev container (or `docker compose run --build --rm tests` from WSL), then run `python -m dmi_ohs.main` twice: the second run should fetch only about the last hour per station.

Not yet completed:

- Scheduled runs (the `app` service fetches once and exits).
- Indoor hardware source/device model.

## Running the services and protecting database data

### What the Docker and PostgreSQL names mean

- **Docker Compose** reads `docker-compose.yml` and starts the containers described there. The project has an `app` service for the pipeline, a `tests` service for pytest, a `db` service running PostgreSQL, and a `pgadmin` service for the database browser.
- **PostgreSQL** is the database server software. The Compose service is named `db`; containers on the Compose network use that name to reach the server.
- **`POSTGRES_HOST`** is the server address. In this project, `.env.example` sets it to `db`. **`POSTGRES_DB`** is the name of one database inside that server; `.env.example` sets it to `postgres_db`. `POSTGRES_PORT` is the server port, normally `5432`.
- The app and tests read these environment variables in `dmi_ohs/database.py`. `docker-compose.yml` passes the values into each container. `${POSTGRES_DB}` means “use the value supplied by the environment or `.env` file.”
- **`postgres_data`** is a Docker-managed persistent volume mounted at PostgreSQL's data directory. PostgreSQL stores its internal files there for all databases on that server. It is storage used by the server, not a database to connect to or a directory to edit by hand.
- **pgAdmin** is a separate web interface that connects to PostgreSQL. It helps browse databases and run queries; it does not store the pipeline's database records. It is available at `http://localhost:8080` while its service is running.

### Dev container and Compose commands

The dev container is a `dev` service in the same Compose project as the database, defined in `.devcontainer/docker-compose.devcontainer.yml`. Only the dev container uses that file, so ordinary `docker compose` commands don't start it. Opening the dev container also starts `db` (`runServices` in `devcontainer.json`), and the dev container reaches it at the host name `db`. The `.env` file must exist before the dev container is opened.

Before this setup, the dev container was built from its Dockerfile alone and was not on the Compose network. Running `docker compose` inside it through docker-outside-of-docker failed, because container paths such as `/workspaces/...` were sent to the host Docker daemon, which could not find them and mounted empty directories instead. Making the dev container a Compose service is the setup VS Code recommends for an app plus a database. The repository should stay in the WSL filesystem (e.g. `/home/<user>/dmi-ohs-data-pipeline`), not under `/mnt/c`, for file performance.

`docker-compose.yml` sets a fixed project name, `dmi-ohs-data-pipeline`, so the dev container and WSL commands share one `db` container and one `postgres_data` volume. The dev container has no Docker CLI, so run `docker compose` commands in a WSL terminal at the project root. `docker compose down` from WSL also stops the dev container's services.

```bash
docker compose run --build --rm app      # fetch new observations into the app database
docker compose run --build --rm tests    # run pytest against the test database
docker compose up -d pgadmin             # pgAdmin at http://localhost:8080
docker compose down                      # stop services
```

Inside the dev container, `pytest` runs all tests and `python -m dmi_ohs.main` fetches into the app database. `tests/conftest.py` always points the tests at `TEST_POSTGRES_DB`, even when `POSTGRES_DB` names the app database (as it does in the dev container, and in terminals that load `.env`). Without it, the tests' `TRUNCATE` could wipe the app data.

After changing `requirements.txt`, rebuild the dev container (**Dev Containers: Rebuild Container**) and use `--build` with `docker compose run`, so both images get the new libraries.

The `app` service uses the default command from `Dockerfile`, `python -m dmi_ohs.main`: it fetches new observations from the DMI API into the database and then exits. Add `--file PATH` to load a saved JSON file instead. To start the database, pgAdmin, and run that app without starting tests, use `docker compose up --build db pgadmin app`. To start only PostgreSQL in the background, use `docker compose up -d db`.

### Test database isolation and initialization

The `app` service connects to `POSTGRES_DB`. The `tests` service connects to a separate database on the same PostgreSQL server, named by `TEST_POSTGRES_DB` (default `dmi_ohs_test`). The integration fixture truncates tables in whichever database the test connection uses, so this separation keeps app rows out of reach of routine test cleanup.

The Postgres image creates the initial database named by `POSTGRES_DB` and runs `database/schema.sql` against it when the data volume is first initialized. The `db` service also passes `TEST_POSTGRES_DB` to `database/init-test-db.sh`. That script creates the second database and applies the same schema file to it. The health check verifies the test schema exists before Compose starts dependent services.

PostgreSQL only runs initialization files when its data directory is empty. To use this new setup with an existing volume, run `docker compose down -v`, then run `docker compose run --build --rm tests`.

**Warning:** `docker compose down -v` deletes `postgres_data`, including both databases and their data, and `pgadmin_data`, including pgAdmin settings. Use it only while those data can be discarded. Ordinary test runs do not delete the app database; the tests only truncate tables in the separate test database.

## Known limitations

- Each run fetches the configured stations once and then exits; nothing schedules repeated runs yet.
- Duplicate measurements under different observation IDs are reported but not resolved.
- PostgreSQL initialization files bootstrap new volumes only. Existing volumes are not updated automatically when the schema evolves.
- Catalog entries are upserted when present, but entries removed from the local catalog are not deleted from PostgreSQL.
- Coverage is collected by the Compose test command, but no minimum threshold is enforced.
- There is no continuous integration workflow yet.

## Recommended next steps

1. Schedule the `app` service to run regularly (for example every 10 minutes, matching DMI's observation frequency).
2. Decide whether catalog synchronization should remove database entries that are no longer in the local catalog.
3. Enforce the 95% coverage target if it remains a project requirement, and add continuous integration.
4. Add the indoor source/device model when the building hardware is available.
