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

### Dev container and Compose commands

The dev container (`.devcontainer/`) is only an editor environment with the Python libraries installed, so VS Code can provide IntelliSense and diagnostics. It is not part of the Compose project and cannot reach the `db` service. Run all `docker compose` commands in a WSL terminal at the project root, outside the dev container. Running Compose inside the dev container sends container paths such as `/workspaces/...` to the host Docker daemon, which cannot find them and creates empty directories in place of bind-mounted files.

```bash
docker compose run --build --rm app      # load sample data into the app database
docker compose run --build --rm tests    # run pytest against the test database
docker compose up -d pgadmin             # pgAdmin at http://localhost:8080
docker compose down                      # stop services
```

Unit tests that need no database can run inside the dev container with `pytest tests/unit`.

The `app` service uses the default command from `Dockerfile`, `python -m dmi_ohs.main`: it loads the bundled sample into the database and then exits. To start the database, pgAdmin, and run that app without starting tests, use `docker compose up --build db pgadmin app`. To start only PostgreSQL in the background, use `docker compose up -d db`.

### Test database isolation and initialization

The `app` service connects to `POSTGRES_DB`. The `tests` service connects to a separate database on the same PostgreSQL server, named by `TEST_POSTGRES_DB` (default `dmi_ohs_test`). The integration fixture truncates tables in whichever database the test connection uses, so this separation keeps app rows out of reach of routine test cleanup.

The Postgres image creates the initial database named by `POSTGRES_DB` and runs `database/schema.sql` against it when the data volume is first initialized. The `db` service also passes `TEST_POSTGRES_DB` to `database/init-test-db.sh`. That script creates the second database and applies the same schema file to it. The health check verifies the test schema exists before Compose starts dependent services.

PostgreSQL only runs initialization files when its data directory is empty. To use this new setup with an existing volume, run `docker compose down -v`, then run `docker compose run --build --rm tests`.

**Warning:** `docker compose down -v` deletes `postgres_data`, including both databases and their data, and `pgadmin_data`, including pgAdmin settings. Use it only while those data can be discarded. Ordinary test runs do not delete the app database; the tests only truncate tables in the separate test database.

## Known limitations

- The pipeline currently consumes saved JSON; it does not make API requests or handle API-specific retries and timeouts.
- PostgreSQL initialization files bootstrap new volumes only. Existing volumes are not updated automatically when the schema evolves.
- Catalog entries are upserted when present, but entries removed from the local catalog are not deleted from PostgreSQL.
- Coverage is collected by the Compose test command, but no minimum threshold is enforced.
- There is no continuous integration workflow yet.

## Recommended next steps

1. Add DMI API extraction with suitable timeout and retry behavior.
2. Decide whether catalog synchronization should remove database entries that are no longer in the local catalog.
3. Enforce the 95% coverage target if it remains a project requirement, and add continuous integration.
4. Add the indoor source/device model when the building hardware is available.
