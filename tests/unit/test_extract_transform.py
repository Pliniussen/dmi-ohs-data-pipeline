import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from dmi_ohs.extract_transform import (
    ExtractError,
    load_catalog,
    parse_observations,
    validate_parameters,
)

FIXTURE = Path(__file__).resolve().parents[2] / "sample_data" / "odense-observations-2026-10-07.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parses_fixture(payload):
    result = parse_observations(payload)

    assert len(result.observations) == len(payload["features"])
    assert len(result.stations) == 1
    station = result.stations[0]
    assert station.station_id == "06120"
    assert (station.longitude, station.latitude) == (Decimal("10.3305"), Decimal("55.4749"))
    first = result.observations[0]
    assert first.parameter_id == "temp_dew"
    assert first.value == Decimal("12.4")
    assert first.observed_at.tzinfo is not None


def test_fixture_parameters_are_in_catalog(payload):
    result = parse_observations(payload)
    validate_parameters(result.observations, load_catalog())


def test_unknown_parameter_is_reported(payload):
    payload["features"][0]["properties"]["parameterId"] = "not_a_parameter"
    result = parse_observations(payload)
    with pytest.raises(ExtractError, match="not_a_parameter"):
        validate_parameters(result.observations, load_catalog())


def test_null_value_is_allowed(payload):
    payload["features"][0]["properties"]["value"] = None
    assert parse_observations(payload).observations[0].value is None


@pytest.mark.parametrize("bad_payload", [[], {}, {"features": []}, {"features": "x"}])
def test_empty_or_malformed_payload(bad_payload):
    with pytest.raises(ExtractError):
        parse_observations(bad_payload)


@pytest.mark.parametrize("field", ["parameterId", "created", "value", "observed", "stationId"])
def test_missing_property(payload, field):
    del payload["features"][0]["properties"][field]
    with pytest.raises(ExtractError, match=field):
        parse_observations(payload)


def test_missing_id_and_geometry(payload):
    no_id = copy.deepcopy(payload)
    del no_id["features"][0]["id"]
    with pytest.raises(ExtractError, match="id"):
        parse_observations(no_id)

    no_geometry = copy.deepcopy(payload)
    del no_geometry["features"][0]["geometry"]
    with pytest.raises(ExtractError, match="geometry"):
        parse_observations(no_geometry)


@pytest.mark.parametrize("timestamp", ["yesterday", "2026-10-07T09:00:00", 5])
def test_invalid_timestamp(payload, timestamp):
    payload["features"][0]["properties"]["observed"] = timestamp
    with pytest.raises(ExtractError):
        parse_observations(payload)


@pytest.mark.parametrize("value", ["12.4", True, [1]])
def test_invalid_value_type(payload, value):
    payload["features"][0]["properties"]["value"] = value
    with pytest.raises(ExtractError, match="value"):
        parse_observations(payload)


@pytest.mark.parametrize("coordinates", [[10.0], "10,55", ["a", "b"]])
def test_invalid_coordinates(payload, coordinates):
    payload["features"][0]["geometry"]["coordinates"] = coordinates
    with pytest.raises(ExtractError):
        parse_observations(payload)


def test_non_string_ids(payload):
    payload["features"][0]["properties"]["parameterId"] = 7
    with pytest.raises(ExtractError):
        parse_observations(payload)


def test_conflicting_station_coordinates(payload):
    payload["features"][1]["geometry"]["coordinates"] = [1.0, 2.0]
    with pytest.raises(ExtractError, match="conflicting"):
        parse_observations(payload)
