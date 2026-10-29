import copy
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from dmi_ohs.database import get_connection
from dmi_ohs.extract_transform import Station, load_catalog, parse_observations
from dmi_ohs.load import latest_observed_at, load
from dmi_ohs import main
from dmi_ohs.api import FetchError
from dmi_ohs.main import PipelineError, run_api, run_file

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

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        load(connection, parsed, catalog)

    connection.rollback()
    assert count(connection, "parameters") == 0
    assert count(connection, "observations") == 0


def test_run_file_loads_sample(connection, parsed):
    result = run_file(FIXTURE)

    assert result.observations == len(parsed.observations)
    assert count(connection, "observations") == len(parsed.observations)


def test_station_move_is_overwritten_with_warning(connection, parsed):
    catalog = load_catalog()
    assert load(connection, parsed, catalog).warnings == []

    moved = replace(parsed, stations=[Station("06120", Decimal("10.3304"), Decimal("55.4748"))])
    result = load(connection, moved, catalog)

    assert any("station 06120 moved" in warning for warning in result.warnings)
    with connection.cursor() as cursor:
        cursor.execute("SELECT longitude, latitude FROM stations WHERE station_id = '06120'")
        assert cursor.fetchone() == (Decimal("10.3304"), Decimal("55.4748"))


def test_duplicate_measurement_is_kept_with_warning(connection, parsed):
    catalog = load_catalog()
    load(connection, parsed, catalog)

    first = parsed.observations[0]
    reissued = replace(parsed, observations=[replace(first, observation_id="reissued-id")])
    result = load(connection, reissued, catalog)

    assert count(connection, "observations") == len(parsed.observations) + 1
    assert any("1 measurements are stored under more than one" in w for w in result.warnings)


def test_latest_observed_at(connection, parsed):
    assert latest_observed_at(connection, "06120") is None
    load(connection, parsed, load_catalog())
    assert latest_observed_at(connection, "06120") == max(o.observed_at for o in parsed.observations)


class FakeFetch:
    """Stands in for fetch_observations and records the requested windows.

    Takes one payload per station; a station mapped to an exception raises it.
    """

    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def __call__(self, station_id, start, end):
        self.calls.append((station_id, start, end))
        payload = self.payloads[station_id]
        if isinstance(payload, Exception):
            raise payload
        return payload


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def as_station(payload, station_id):
    """Copy the Odense payload as if it came from another station."""
    copied = copy.deepcopy(payload)
    for feature in copied["features"]:
        feature["id"] = f"{station_id}-{feature['id']}"
        feature["properties"]["stationId"] = station_id
        feature["geometry"]["coordinates"] = [12.0, 56.0]
    return copied


def test_run_api_resumes_after_latest_observation(connection, parsed, payload, monkeypatch):
    monkeypatch.setenv("DMI_STATION_IDS", "06120")
    monkeypatch.setenv("DMI_INITIAL_LOOKBACK_HOURS", "24")
    fetch = FakeFetch({"06120": payload})

    before = datetime.now(timezone.utc)
    run_api(fetch=fetch)
    run_api(fetch=fetch)

    (_, first_start, first_end), (_, second_start, _) = fetch.calls
    assert first_end >= before
    assert first_end - first_start == timedelta(hours=24)
    latest = max(o.observed_at for o in parsed.observations)
    assert second_start == latest - timedelta(hours=1)
    # The overlapping second load must not duplicate rows.
    assert count(connection, "observations") == len(parsed.observations)


def test_run_api_loads_each_station_with_its_own_window(connection, parsed, payload, monkeypatch):
    monkeypatch.setenv("DMI_STATION_IDS", "06120, 06180")
    load(connection, parsed, load_catalog())
    fetch = FakeFetch({"06120": payload, "06180": as_station(payload, "06180")})

    results = run_api(fetch=fetch)

    assert list(results) == ["06120", "06180"]
    (first_id, first_start, _), (second_id, second_start, second_end) = fetch.calls
    latest = max(o.observed_at for o in parsed.observations)
    # 06120 already has rows, so it continues; 06180 is new, so it uses the lookback.
    assert (first_id, first_start) == ("06120", latest - timedelta(hours=1))
    assert second_id == "06180"
    assert second_end - second_start == timedelta(hours=24)
    assert count(connection, "stations") == 2
    assert count(connection, "observations") == 2 * len(parsed.observations)


def test_run_api_continues_after_a_failing_station(connection, parsed, payload, monkeypatch, capsys):
    monkeypatch.setenv("DMI_STATION_IDS", "06180,06120")
    fetch = FakeFetch({"06180": FetchError("DMI is down"), "06120": payload})

    with pytest.raises(PipelineError, match="06180"):
        run_api(fetch=fetch)

    # The failing station did not stop the other one from loading.
    assert count(connection, "observations") == len(parsed.observations)
    assert "station 06180 failed: DMI is down" in capsys.readouterr().err


def test_run_api_continues_after_a_database_error(connection, parsed, payload, monkeypatch, capsys):
    monkeypatch.setenv("DMI_STATION_IDS", "06180,06120")
    fetch = FakeFetch({"06180": as_station(payload, "06180"), "06120": payload})
    real_load_payload = main.load_payload

    def failing_load_payload(conn, station_payload, catalog):
        # Write some rows first, so the test also checks that they are rolled back.
        if station_payload["features"][0]["properties"]["stationId"] == "06180":
            with conn.transaction():
                real_load_payload(conn, station_payload, catalog)
                raise psycopg.errors.CheckViolation("simulated constraint error")
        return real_load_payload(conn, station_payload, catalog)

    monkeypatch.setattr(main, "load_payload", failing_load_payload)

    with pytest.raises(PipelineError, match="06180"):
        run_api(fetch=fetch)

    # 06180's rows were rolled back, and 06120 still loaded on the same connection.
    with connection.cursor() as cursor:
        cursor.execute("SELECT DISTINCT station_id FROM observations")
        assert cursor.fetchall() == [("06120",)]
    assert count(connection, "observations") == len(parsed.observations)
    assert "station 06180 failed: simulated constraint error" in capsys.readouterr().err


def test_run_api_with_no_new_observations(connection, monkeypatch):
    monkeypatch.setenv("DMI_STATION_IDS", "06120")
    results = run_api(fetch=FakeFetch({"06120": {"type": "FeatureCollection", "features": []}}))

    assert results == {"06120": None}
    assert count(connection, "observations") == 0


def test_run_api_skips_unknown_parameters(connection, parsed, payload, monkeypatch, capsys):
    monkeypatch.setenv("DMI_STATION_IDS", "06120")
    changed = copy.deepcopy(payload)
    changed["features"][0]["properties"]["parameterId"] = "not_a_parameter"

    result = run_api(fetch=FakeFetch({"06120": changed}))["06120"]

    assert result is not None
    assert result.observations == len(parsed.observations) - 1
    assert count(connection, "observations") == len(parsed.observations) - 1
    assert "not_a_parameter" in capsys.readouterr().err
