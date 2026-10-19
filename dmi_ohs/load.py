from dataclasses import dataclass

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


@dataclass(frozen=True)
class LoadResult:
    """How many input rows were written (inserted or updated) per table."""

    parameters: int
    value_codes: int
    stations: int
    observations: int


def load(connection, parsed: ParsedObservations, catalog: dict) -> LoadResult:
    """Upsert catalog reference data, stations and observations in one transaction.

    Rows are written parents-first because of the foreign keys. Any failure
    rolls the whole load back, and re-running the same load is harmless
    because every statement is an upsert.
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

    # transaction() commits on success and rolls back if anything raises.
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.executemany(UPSERT_PARAMETER, parameter_rows)
            cursor.executemany(UPSERT_VALUE_CODE, code_rows)
            cursor.executemany(UPSERT_STATION, station_rows)
            cursor.executemany(UPSERT_OBSERVATION, observation_rows)

    return LoadResult(
        parameters=len(parameter_rows),
        value_codes=len(code_rows),
        stations=len(station_rows),
        observations=len(observation_rows),
    )
