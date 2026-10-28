import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from dmi_ohs.extract_transform import (
    CATALOG_PATH,
    ExtractError,
    filter_known_parameters,
    load_catalog,
    parse_observations,
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
    kept, unknown = filter_known_parameters(result.observations, load_catalog())
    assert kept == result.observations
    assert unknown == []


def test_unknown_parameters_are_skipped(payload):
    payload["features"][0]["properties"]["parameterId"] = "not_a_parameter"
    payload["features"][1]["properties"]["parameterId"] = "also_unknown"
    result = parse_observations(payload)
    kept, unknown = filter_known_parameters(result.observations, load_catalog())
    assert unknown == ["also_unknown", "not_a_parameter"]
    assert kept == result.observations[2:]


@pytest.fixture
def catalog_file(tmp_path):
    def write(catalog):
        path = tmp_path / "catalog.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        return path

    return write


@pytest.fixture
def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", ["parameters", "code_sets"])
def test_catalog_missing_section(catalog, catalog_file, key):
    del catalog[key]
    with pytest.raises(ExtractError, match=key):
        load_catalog(catalog_file(catalog))


@pytest.mark.parametrize("key", ["description", "unit", "frequency"])
def test_catalog_parameter_missing_field(catalog, catalog_file, key):
    del catalog["parameters"]["temp_dew"][key]
    with pytest.raises(ExtractError, match=f"temp_dew.*{key}"):
        load_catalog(catalog_file(catalog))


def test_catalog_description_must_be_a_list(catalog, catalog_file):
    catalog["parameters"]["temp_dew"]["description"] = "one line"
    with pytest.raises(ExtractError, match="description must be a list"):
        load_catalog(catalog_file(catalog))


def test_catalog_code_set_needs_parameter(catalog, catalog_file):
    catalog["code_sets"]["not_a_parameter"] = {"0": "Zero"}
    with pytest.raises(ExtractError, match="not_a_parameter"):
        load_catalog(catalog_file(catalog))


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


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_value(payload, value):
    payload["features"][0]["properties"]["value"] = value
    with pytest.raises(ExtractError, match="finite"):
        parse_observations(payload)


@pytest.mark.parametrize("coordinates", [[10.0], "10,55", ["a", "b"]])
def test_invalid_coordinates(payload, coordinates):
    payload["features"][0]["geometry"]["coordinates"] = coordinates
    with pytest.raises(ExtractError, match="coordinates"):
        parse_observations(payload)


@pytest.mark.parametrize(
    "coordinates",
    [[181, 0], [-181, 0], [0, 91], [0, -91], [float("nan"), 0], [0, float("inf")]],
)
def test_coordinates_out_of_range(payload, coordinates):
    payload["features"][0]["geometry"]["coordinates"] = coordinates
    with pytest.raises(ExtractError, match="out of range"):
        parse_observations(payload)


@pytest.mark.parametrize("coordinates", [[-180, -90], [180, 90]])
def test_coordinate_range_endpoints_are_allowed(payload, coordinates):
    for feature in payload["features"]:
        feature["geometry"]["coordinates"] = coordinates
    station = parse_observations(payload).stations[0]
    assert station.longitude == Decimal(str(coordinates[0]))
    assert station.latitude == Decimal(str(coordinates[1]))


def test_station_id_must_be_a_string(payload):
    payload["features"][0]["properties"]["stationId"] = 6120
    with pytest.raises(ExtractError, match="stationId must be a string"):
        parse_observations(payload)


def test_non_string_ids(payload):
    payload["features"][0]["properties"]["parameterId"] = 7
    with pytest.raises(ExtractError):
        parse_observations(payload)


def test_conflicting_station_coordinates_use_latest(payload):
    # feature[0] and feature[1] share the latest observed time; the first one seen wins.
    payload["features"][1]["geometry"]["coordinates"] = [1.0, 2.0]
    result = parse_observations(payload)
    station = result.stations[0]
    assert (station.longitude, station.latitude) == (Decimal("10.3305"), Decimal("55.4749"))
    assert len(result.warnings) == 1
    assert "conflicting coordinates" in result.warnings[0]


def test_conflicting_station_coordinates_newer_feature_wins(payload):
    payload["features"][-1]["geometry"]["coordinates"] = [1.0, 2.0]
    payload["features"][-1]["properties"]["observed"] = "2030-01-01T00:00:00Z"
    station = parse_observations(payload).stations[0]
    assert (station.longitude, station.latitude) == (Decimal("1.0"), Decimal("2.0"))


def test_no_warnings_for_consistent_input(payload):
    assert parse_observations(payload).warnings == []
