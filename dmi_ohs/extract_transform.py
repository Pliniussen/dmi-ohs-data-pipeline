import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# Find the catalog next to the project files, no matter where the program starts.
CATALOG_PATH = Path(__file__).resolve().parent.parent / "reference_data" / "dmi-parameter-catalog.json"


class ExtractError(ValueError):
    """An error caused by bad input data."""

    pass


@dataclass(frozen=True)
class Station:
    """A station's ID and location."""

    station_id: str
    longitude: Decimal
    latitude: Decimal


@dataclass(frozen=True)
class Observation:
    """One measurement reported for one parameter at one time and station."""

    observation_id: str
    station_id: str
    parameter_id: str
    observed_at: datetime
    created_at: datetime
    value: Decimal | None


@dataclass(frozen=True)
class ParsedObservations:
    """The stations and measurements read from the input."""

    stations: list[Station]
    observations: list[Observation]


def _require(mapping: Any, key: str, where: str) -> Any:
    # Check that this is an object and that it has the requested field.
    # This gives a clear input error instead of a confusing Python error later.
    if not isinstance(mapping, dict) or key not in mapping:
        raise ExtractError(f"{where}: missing field '{key}'")
    return mapping[key]


def _parse_timestamp(raw: Any, where: str) -> datetime:
    # The timestamp must be text and include a timezone. Without one,
    # a time like 09:00 could mean different things in different places.
    if not isinstance(raw, str):
        raise ExtractError(f"{where}: timestamp must be a string")
    try:
        # Python expects "+00:00", while the input may use "Z" for UTC.
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ExtractError(f"{where}: invalid timestamp '{raw}'") from error
    if parsed.tzinfo is None:
        raise ExtractError(f"{where}: timestamp '{raw}' has no timezone")
    return parsed


def _parse_value(raw: Any, where: str) -> Decimal | None:
    # A missing measurement is null in JSON and None in Python. It is not zero.
    if raw is None:
        return None
    # Python treats True and False like numbers, but they are not measurements.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ExtractError(f"{where}: value must be a number or null")
    # Convert through text so Decimal does not inherit float rounding noise.
    value = Decimal(str(raw))
    if not value.is_finite():
        raise ExtractError(f"{where}: value must be a finite number or null")
    return value


def _parse_station(feature: dict, where: str) -> Station:
    # Station fields are split between GeoJSON's "properties" and "geometry".
    properties = _require(feature, "properties", where)
    station_id = _require(properties, "stationId", where)
    geometry = _require(feature, "geometry", where)
    coordinates = _require(geometry, "coordinates", where)
    if not isinstance(station_id, str):
        raise ExtractError(f"{where}: stationId must be a string")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise ExtractError(f"{where}: coordinates must include longitude and latitude")
    if not all(
        isinstance(coordinate, (int, float)) and not isinstance(coordinate, bool)
        for coordinate in coordinates[:2]
    ):
        raise ExtractError(f"{where}: coordinates must contain numeric longitude and latitude")
    # GeoJSON order is [longitude, latitude].
    longitude = Decimal(str(coordinates[0]))
    latitude = Decimal(str(coordinates[1]))
    if (
        not longitude.is_finite()
        or not latitude.is_finite()
        or not -180 <= longitude <= 180
        or not -90 <= latitude <= 90
    ):
        raise ExtractError(
            f"{where}: coordinates out of range (longitude: -180 to 180, latitude: -90 to 90)"
        )
    return Station(
        station_id=station_id,
        longitude=longitude,
        latitude=latitude,
    )


def parse_observations(payload: Any) -> ParsedObservations:
    """Check the input and turn each feature into Python records.

    Many measurements can come from one station, so each station is returned
    once while every measurement is kept.
    """
    # The input must contain at least one feature.
    features = _require(payload, "features", "payload")
    if not isinstance(features, list) or not features:
        raise ExtractError("payload: no observation features")

    # Keep one station per ID so we can spot conflicting locations.
    stations: dict[str, Station] = {}
    # Keep every observation; each feature is a separate measurement.
    observations: list[Observation] = []

    # Include the feature number in errors to help find bad input.
    for index, feature in enumerate(features):
        where = f"feature[{index}]"
        properties = _require(feature, "properties", where)
        station = _parse_station(feature, where)

        # Save the station the first time we see its ID.
        known = stations.setdefault(station.station_id, station)
        if known != station:
            raise ExtractError(f"{where}: conflicting coordinates for station {station.station_id}")

        # These IDs tell us which parameter was measured and identify the record.
        parameter_id = _require(properties, "parameterId", where)
        observation_id = _require(feature, "id", where)
        if not isinstance(parameter_id, str) or not isinstance(observation_id, str):
            raise ExtractError(f"{where}: id and parameterId must be strings")

        # Check and convert the values now so later code can use them directly.
        observations.append(
            Observation(
                observation_id=observation_id,
                station_id=station.station_id,
                parameter_id=parameter_id,
                observed_at=_parse_timestamp(_require(properties, "observed", where), where),
                created_at=_parse_timestamp(_require(properties, "created", where), where),
                value=_parse_value(_require(properties, "value", where), where),
            )
        )

    # Return the unique stations and all observations as lists.
    return ParsedObservations(list(stations.values()), observations)


def load_catalog(path: Path = CATALOG_PATH) -> dict:
    """Read and decode the JSON catalog that defines valid parameter IDs."""
    return json.loads(path.read_text(encoding="utf-8"))


def validate_parameters(observations: list[Observation], catalog: dict) -> None:
    """Fail if any observation uses a parameter absent from the catalog.

    The catalog's "parameters" keys are the allowed parameter IDs. Sort the
    unknown IDs so the error message is always in the same order.
    """
    known = catalog["parameters"]
    missing = sorted({o.parameter_id for o in observations} - set(known))
    if missing:
        raise ExtractError(f"parameters missing from catalog: {', '.join(missing)}")
