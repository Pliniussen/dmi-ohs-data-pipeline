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

The `app` service runs these steps once and exits. The `collector` service (`python -m dmi_ohs.main --every MINUTES`) repeats them every `DMI_RUN_INTERVAL_MINUTES`; see [Scheduled collection](#scheduled-collection).

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
- **One transaction per station.** A station that fails (API error, bad data or a database error) does not roll back or block the others. The run still exits with an error, so a scheduler can notice.
- **Scheduling as a Python loop in a Compose service, not cron or a host scheduler.** The loop is plain Python and unit-tested, needs no extra image, and shows up in Docker Desktop next to the other services. It keeps going when a run fails because of the API or the database; any other error stops it, so a bug shows up as an exited container.
- **The collector is started by hand (`restart: "no"`).** When Docker restarts containers itself, it doesn't go through Compose, so `depends_on` is ignored and `db` stays stopped. That rules out `unless-stopped`, and also `on-failure`: tested on 2026-10-29, a Docker Desktop restart kills the containers with exit code 255, Docker counts that as a failure, and it brought the collector back without `db`. Starting it with `docker compose up -d collector` always starts `db` first. The cost is that a crash from a bug is not restarted, but API and database problems don't crash the loop. Not running costs no data, because the next run fills the gap from the newest stored row.

### DMI API behaviour

Observed on `https://opendataapi.dmi.dk/v2/metObs/collections/observation/items`:

- No API key is required.
- Results are sorted newest first.
- The `datetime=start/end` range includes both ends; a 08:00–09:00 query returns rows observed at 08:00 and at 09:00.
- A `next` link is included even on the last, short page, so paging stops on page size instead (`limit=10000`, normally one page per run).
- Station coordinates are taken from the observation features. The station API (`.../collections/station/items`) is not called; `sample_data/odense-station.json` shows that station 06120 has had several coordinate periods since 1959.
- Observations are published quickly: in the first 24 hours loaded (2026-10-28/29), `created - observed` was about 25 s median and under 40 s for every parameter, so the one-hour overlap has a large margin.
- Station 06120 reports 24 of the 51 catalog parameters, about 86 rows per hour. `weather` and `cloud_height` are only reported some of the time, so the number of rows per hour varies (80–92).

## Configuration

Settings come from environment variables, which Compose reads from `.env`. `.env` is not committed; `.env.example` is its template, and both should contain the same keys so it is clear which settings are in effect. The code has defaults for the DMI settings, but they should still be written in `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `DMI_STATION_IDS` | `06120` | Comma-separated DMI station IDs to fetch, e.g. `06120,06180`. Kept as text because the leading zero is part of the ID. |
| `DMI_INITIAL_LOOKBACK_HOURS` | `24` | How far back to fetch for a station with no stored observations (first run, or newly added station). Ignored once the station has data. Set it higher (e.g. `720` for 30 days) before the first run to start with more history. Must be a positive number. |
| `DMI_RUN_INTERVAL_MINUTES` | `10` | Minutes between the start of one `collector` run and the next. Must be a positive number. |
| `POSTGRES_USER` | `admin` | Database user. Keep `admin`: `pgadmin/servers.json` connects with that name and cannot read environment variables. |
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
- The saved API responses are strict JSON. Each one records the request that produced it in its `links` list, under `"rel": "self"`. To refresh a fixture, run from the project root `curl --silent "<self URL>" | python3 -m json.tool > sample_data/<file>.json`.

Source documentation:  
https://www.dmi.dk/friedata/dokumentation/meteorological-observations-data  
https://www.dmi.dk/friedata/dokumentation/meteorological-observation-api

## Current implementation status

Completed:

- PostgreSQL and Docker Compose development environment.
- Station, parameter, value-code, and observation tables with foreign keys. Observation IDs are unique; duplicate measurements under different IDs are only warned about.
- Schema bootstrap wiring through PostgreSQL's initialization directory.
- JSON parsing and validation for observation features, station coordinates, timestamps, and values.
- Validation of the catalog's structure, and skipping (with a warning) of observations whose parameter is missing from it.
- Transactional, idempotent upserts for catalog data, stations, and observations, with warnings for moved stations and duplicate measurements.
- Incremental fetching from the DMI observation API with pagination, timeouts, and retries.
- A command-line pipeline that fetches from the API by default or loads a JSON file with `--file`, then reports input row counts submitted to the upserts.
- Clean error messages, without a traceback, for invalid settings and unreadable or invalid `--file` input.
- Scheduled collection: the `collector` service runs the pipeline every `DMI_RUN_INTERVAL_MINUTES` with `--every`.
- Unit tests for parsing, input and catalog validation, settings, file errors, the scheduling loop, and the API client (using a fake HTTP session), plus PostgreSQL integration tests for connectivity, loading, repeat loads, rollback, warnings, per-station failures (API and database errors), and the incremental fetch window.

Verified on 2026-10-29 (WSL, fresh volume):

- `docker compose run --build --rm tests`: all tests passed against PostgreSQL, with 95% coverage.
- Two real API runs for 06120. The first loaded 2,062 observations (24-hour lookback). The second loaded 95, all of them overlap rows that were already stored. No warnings were printed.
- Queries A–D in [Checking the data](#checking-the-data) found no gaps and no duplicate measurements. The longest publishing delay was 36 s.

Not yet verified:

- The `collector` service has unit tests for its loop but has not yet run in Docker.

Not yet completed:

- Visualisation dashboard.
- Indoor hardware source/device model.

## Running the services and protecting database data

### What the Docker and PostgreSQL names mean

- **Docker Compose** reads `docker-compose.yml` and starts the containers described there. The project has an `app` service that runs the pipeline once, a `collector` service that runs it on a schedule, a `tests` service for pytest, a `db` service running PostgreSQL, and a `pgadmin` service for the database browser.
- **PostgreSQL** is the database server software. The Compose service is named `db`; containers on the Compose network use that name to reach the server. Its port is not published to the host: everything that uses the database runs as a Compose service. A future dashboard should do the same, connecting to `db:5432` and publishing only its own web port (e.g. `127.0.0.1:3000:3000`). For `psql`, use `docker compose exec db psql -U admin -d postgres_db`.
- **`POSTGRES_HOST`** is the server address. In this project, `.env.example` sets it to `db`. **`POSTGRES_DB`** is the name of one database inside that server; `.env.example` sets it to `postgres_db`. `POSTGRES_PORT` is the server port, normally `5432`.
- The app and tests read these environment variables in `dmi_ohs/database.py`. `docker-compose.yml` passes the values into each container. `${POSTGRES_DB}` means “use the value supplied by the environment or `.env` file.”
- **`postgres_data`** is a Docker-managed persistent volume mounted at PostgreSQL's data directory. PostgreSQL stores its internal files there for all databases on that server. It is storage used by the server, not a database to connect to or a directory to edit by hand.
- **pgAdmin** is a separate web interface that connects to PostgreSQL. It helps browse databases and run queries; it does not store the pipeline's database records. It is available at `http://localhost:8080` (this machine only) while its service is running.

### Dev container and Compose commands

The dev container is built from `.devcontainer/Dockerfile` alone and is used for editing (IntelliSense and linting). It is not part of the Compose project and cannot reach `db`, so only `pytest tests/unit` runs inside it. It has no Docker CLI; run `docker compose` commands in a WSL terminal at the project root. The repository should stay in the WSL filesystem (e.g. `/home/<user>/dmi-ohs-data-pipeline`), not under `/mnt/c`, for file performance.

The dev container runs as a non-root `vscode` user (`remoteUser` in `devcontainer.json`). Dev Containers sets that user's UID to the host user's, so files saved in the container stay owned by the WSL user. An earlier root-run container left root-owned files that WSL tools could not edit.

The dev container was briefly a Compose service on the same network as `db`. That setup was reverted because rebuilding it fails with Docker Compose 5.6.1 and Buildx ≥0.37.2: Compose builds through Buildx bake, bake now enforces filesystem entitlements, and Compose does not grant read access to the `Dockerfile-with-features` that the Dev Containers CLI writes to `/tmp`, outside the build context. `COMPOSE_BAKE=false` has no effect in Compose 5, and `BUILDX_BAKE_ENTITLEMENTS_FS=0` works only by disabling the check on each developer's machine. The bug is docker/compose#14285, fixed by docker/compose#14325 but not in a release yet. A dev container built from its own Dockerfile uses `docker buildx build`, which is not affected.

```bash
docker compose run --build --rm app      # fetch new observations into the app database once
docker compose up -d --build collector   # keep fetching every DMI_RUN_INTERVAL_MINUTES
docker compose logs -f collector         # follow the collector's output
docker compose stop collector            # stop scheduled collection
docker compose run --build --rm tests    # run pytest against the test database
docker compose up -d pgadmin             # pgAdmin at http://localhost:8080
docker compose down                      # stop services
```

`tests/conftest.py` always points the tests at `TEST_POSTGRES_DB`, even when `POSTGRES_DB` names the app database (as it does in terminals that load `.env`). Without it, the tests' `TRUNCATE` could wipe the app data.

After changing `requirements.txt`, rebuild the dev container (**Dev Containers: Rebuild Container**) and use `--build` with `docker compose run`, so both images get the new libraries.

The `app` service uses the default command from `Dockerfile`, `python -m dmi_ohs.main`: it fetches new observations from the DMI API into the database and then exits. Add `--file PATH` to load a saved JSON file instead. To start the database, pgAdmin, and run that app without starting tests, use `docker compose up --build db pgadmin app`. To start only PostgreSQL in the background, use `docker compose up -d db`.

### Scheduled collection

The `collector` service runs `python -m dmi_ohs.main --every ${DMI_RUN_INTERVAL_MINUTES:-10}`. Each run prints `Run started at …`, one line per station, and `Next run at …`. Runs keep a fixed rhythm: the next one starts one interval after the previous one started, and a run that takes longer than the interval skips the slots it overran instead of running several times back to back. The settings are checked once at startup, so a bad `.env` stops the collector immediately with an error.

- A run that fails because of the DMI API or the database is reported as a warning, and the collector waits for the next run.
- Any other error stops the process, and Docker does not restart it (`restart: "no"`). The container then shows as *Exited* in Docker Desktop, and `docker compose logs collector` shows the error.
- `init: true` passes `docker compose stop`'s signal to Python, so the collector stops straight away instead of after Docker's 10-second timeout.
- `PYTHONUNBUFFERED=1` in `Dockerfile` makes the output appear in the logs immediately.
- The collector does not start on its own after a PC or Docker Desktop restart. Start it with `docker compose up -d collector`; the first run fills the gap.
- `--every` and `--file` cannot be combined. `app` and `collector` can run at the same time, because every load is an upsert.

### Test database isolation and initialization

The `app` service connects to `POSTGRES_DB`. The `tests` service connects to a separate database on the same PostgreSQL server, named by `TEST_POSTGRES_DB` (default `dmi_ohs_test`). The integration fixture truncates tables in whichever database the test connection uses, so this separation keeps app rows out of reach of routine test cleanup.

The Postgres image creates the initial database named by `POSTGRES_DB` and runs `database/schema.sql` against it when the data volume is first initialized. The `db` service also passes `TEST_POSTGRES_DB` to `database/init-test-db.sh`. That script creates the second database and applies the same schema file to it. The health check verifies the test schema exists before Compose starts dependent services.

PostgreSQL only runs initialization files when its data directory is empty. To use this new setup with an existing volume, run `docker compose down -v`, then run `docker compose run --build --rm tests`.

**Warning:** `docker compose down -v` deletes `postgres_data`, including both databases and their data, and `pgadmin_data`, including pgAdmin settings. Use it only while those data can be discarded. Ordinary test runs do not delete the app database; the tests only truncate tables in the separate test database.

## Checking the data

Run these queries against the app database after a few days of collection and whenever a station is added. Either:

- open pgAdmin (`docker compose up -d pgadmin`, http://localhost:8080), expand *Servers → Postgres → Databases → postgres_db*, right-click it, choose **Query Tool**, paste a query and press **F5**; or
- run `docker compose exec db psql -U admin -d postgres_db` in WSL and paste the query.

**A. Coverage per station.** Expect one row per station, with `latest` close to the time of the last run.

```sql
SELECT station_id, count(*) AS rows, min(observed_at) AS earliest, max(observed_at) AS latest
FROM observations
GROUP BY station_id;
```

**B. Publishing delay per parameter.** `created_at - observed_at` is how long DMI took to publish a measurement. A parameter whose `max_delay` is longer than the one-hour overlap (`OVERLAP` in `dmi_ohs/main.py`) can be missed by the incremental fetch window.

```sql
SELECT o.parameter_id, p.frequency, count(*) AS rows,
       max(o.observed_at) AS latest,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY o.created_at - o.observed_at) AS median_delay,
       max(o.created_at - o.observed_at) AS max_delay
FROM observations o
JOIN parameters p USING (parameter_id)
GROUP BY o.parameter_id, p.frequency
ORDER BY max_delay DESC;
```

**C. Gaps per hour.** Full hours should have about the same `rows` and `parameters`. Only the first and newest hours are partial. A dip in between means rows were missed between runs.

```sql
SELECT date_trunc('hour', observed_at) AS hour,
       count(*) AS rows, count(DISTINCT parameter_id) AS parameters
FROM observations
WHERE station_id = '06120'
GROUP BY 1
ORDER BY 1;
```

**D. Duplicate measurements.** This should be empty. Any rows show that DMI re-issued a measurement under a new ID (see the design decisions).

```sql
SELECT station_id, parameter_id, observed_at, count(*) AS n,
       array_agg(observation_id ORDER BY created_at) AS ids,
       array_agg(value ORDER BY created_at) AS values
FROM observations
GROUP BY station_id, parameter_id, observed_at
HAVING count(*) > 1;
```

## Known limitations

- Scheduled collection runs only while the `collector` service is running. It has to be started again after a PC or Docker Desktop restart; nothing is lost, but the data is not current until it runs.
- Duplicate measurements under different observation IDs are reported but not resolved.
- PostgreSQL initialization files bootstrap new volumes only. Existing volumes are not updated automatically when the schema evolves.
- Catalog entries are upserted when present, but entries removed from the local catalog are not deleted from PostgreSQL.
- Coverage is collected by the Compose test command, but no minimum threshold is enforced.
- There is no continuous integration workflow yet.

## Recommended next steps

1. Build the visualisation dashboard as a Compose service that reads from `db:5432`.
2. Decide whether catalog synchronization should remove database entries that are no longer in the local catalog.
3. Enforce the 95% coverage target if it remains a project requirement, and add continuous integration.
4. Add the indoor source/device model when the building hardware is available.
