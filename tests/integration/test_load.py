import json
from pathlib import Path

import pytest

from dmi_ohs.database import get_connection
from dmi_ohs.extract_transform import load_catalog, parse_observations
from dmi_ohs.load import load

FIXTURE = Path(__file__).resolve().parents[2] / "sample_data" / "odense-observations-2026-10-07.json"
TABLES = ["observations", "parameter_value_codes", "parameters", "stations"]


@pytest.fixture
def connection():
    connection = get_connection()
    clear(connection)
    yield connection
    clear(connection)
    connection.close()


def clear(connection):
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE {', '.join(TABLES)}")
    connection.commit()


def count(connection, table):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table}")
        return cursor.fetchone()[0]


@pytest.fixture
def parsed():
    return parse_observations(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_load_populates_tables(connection, parsed):
    catalog = load_catalog()
    result = load(connection, parsed, catalog)

    assert result.observations == len(parsed.observations)
    assert count(connection, "observations") == len(parsed.observations)
    assert count(connection, "stations") == 1
    assert count(connection, "parameters") == len(catalog["parameters"])
    assert count(connection, "parameter_value_codes") == result.value_codes


def test_load_is_idempotent(connection, parsed):
    catalog = load_catalog()
    load(connection, parsed, catalog)
    load(connection, parsed, catalog)

    assert count(connection, "observations") == len(parsed.observations)
    assert count(connection, "stations") == 1


def test_failed_load_rolls_back(connection, parsed):
    catalog = load_catalog()
    del catalog["parameters"]["temp_dew"]

    with pytest.raises(Exception):
        load(connection, parsed, catalog)

    connection.rollback()
    assert count(connection, "parameters") == 0
    assert count(connection, "observations") == 0


def test_main_run_loads_sample(connection, parsed):
    from dmi_ohs.main import run

    result = run(FIXTURE)

    assert result.observations == len(parsed.observations)
    assert count(connection, "observations") == len(parsed.observations)
