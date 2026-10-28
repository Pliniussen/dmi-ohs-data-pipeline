from dataclasses import dataclass, field
from datetime import datetime

from dmi_ohs.extract_transform import ParsedObservations

UPSERT_PARAMETER = """
    INSERT INTO parameters (parameter_id, description, unit, frequency)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (parameter_id) DO UPDATE SET
        description = EXCLUDED.description,
        unit = EXCLUDED.unit,
        frequency = EXCLUDED.frequency
"""

UPSERT_VALUE_CODE = """
    INSERT INTO parameter_value_codes (parameter_id, code, description)
    VALUES (%s, %s, %s)
    ON CONFLICT (parameter_id, code) DO UPDATE SET
        description = EXCLUDED.description
"""

SELECT_STATIONS = """
    SELECT station_id, longitude, latitude
    FROM stations
    WHERE station_id = ANY(%s)
"""

UPSERT_STATION = """
    INSERT INTO stations (station_id, longitude, latitude)
    VALUES (%s, %s, %s)
    ON CONFLICT (station_id) DO UPDATE SET
        longitude = EXCLUDED.longitude,
        latitude = EXCLUDED.latitude
"""

UPSERT_OBSERVATION = """
    INSERT INTO observations
        (observation_id, station_id, parameter_id, observed_at, created_at, value)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (observation_id) DO UPDATE SET
        station_id = EXCLUDED.station_id,
        parameter_id = EXCLUDED.parameter_id,
        observed_at = EXCLUDED.observed_at,
        created_at = EXCLUDED.created_at,
        value = EXCLUDED.value
"""

# Rows with different IDs that describe the same measurement, e.g. if DMI
# re-issues a corrected value under a new ID.
SELECT_DUPLICATE_MEASUREMENTS = """
    SELECT station_id, parameter_id, observed_at, count(*)
    FROM observations
    WHERE station_id = ANY(%s) AND observed_at BETWEEN %s AND %s
    GROUP BY station_id, parameter_id, observed_at
    HAVING count(*) > 1
    ORDER BY observed_at, station_id, parameter_id
"""

SELECT_LATEST_OBSERVED_AT = """
    SELECT max(observed_at) FROM observations WHERE station_id = %s
"""


@dataclass(frozen=True)
class LoadResult:
    """How many input rows were submitted to upsert per table, plus any warnings."""

    parameters: int
    value_codes: int
    stations: int
    observations: int
    warnings: list[str] = field(default_factory=list)


def latest_observed_at(connection, station_id: str) -> datetime | None:
    """Return the newest stored observation time for a station, or None if it has none."""
    # Run the read in its own transaction so a later load() is not nested in it
    # as a savepoint, which would leave the load uncommitted.
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(SELECT_LATEST_OBSERVED_AT, (station_id,))
            return cursor.fetchone()[0]


def load(connection, parsed: ParsedObservations, catalog: dict) -> LoadResult:
    """Upsert catalog reference data, stations and observations in one transaction.

    Rows are written parents-first because of the foreign keys. Any failure
    rolls the whole load back, and re-running the same load is harmless
    because every statement is an upsert. Moved stations and duplicate
    measurements are written anyway and reported as warnings.
    """
    parameter_rows = [
        (parameter_id, " ".join(meta["description"]), meta["unit"], meta["frequency"])
        for parameter_id, meta in catalog["parameters"].items()
    ]
    code_rows = [
        (parameter_id, code, description)
        for parameter_id, codes in catalog["code_sets"].items()
        for code, description in codes.items()
    ]
    station_rows = [
        (s.station_id, s.longitude, s.latitude)
        for s in parsed.stations
    ]
    observation_rows = [
        (o.observation_id, o.station_id, o.parameter_id, o.observed_at, o.created_at, o.value)
        for o in parsed.observations
    ]
    station_ids = [s.station_id for s in parsed.stations]
    warnings = []

    # transaction() commits on success and rolls back if anything raises.
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.executemany(UPSERT_PARAMETER, parameter_rows)
            cursor.executemany(UPSERT_VALUE_CODE, code_rows)

            cursor.execute(SELECT_STATIONS, (station_ids,))
            stored = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
            for s in parsed.stations:
                old = stored.get(s.station_id)
                if old is not None and old != (s.longitude, s.latitude):
                    warnings.append(
                        f"station {s.station_id} moved from ({old[0]}, {old[1]}) "
                        f"to ({s.longitude}, {s.latitude})"
                    )
            cursor.executemany(UPSERT_STATION, station_rows)

            cursor.executemany(UPSERT_OBSERVATION, observation_rows)
            if parsed.observations:
                observed = [o.observed_at for o in parsed.observations]
                cursor.execute(
                    SELECT_DUPLICATE_MEASUREMENTS, (station_ids, min(observed), max(observed))
                )
                duplicates = cursor.fetchall()
                if duplicates:
                    examples = "; ".join(
                        f"{station_id}/{parameter_id} at {observed_at.isoformat()} ({n} rows)"
                        for station_id, parameter_id, observed_at, n in duplicates[:3]
                    )
                    warnings.append(
                        f"{len(duplicates)} measurements are stored under more than one "
                        f"observation ID, e.g. {examples}"
                    )

    return LoadResult(
        parameters=len(parameter_rows),
        value_codes=len(code_rows),
        stations=len(station_rows),
        observations=len(observation_rows),
        warnings=warnings,
    )
