import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# The parameter catalog is stored beside the application package, not in the
# current working directory. Resolving from this file makes the path reliable
# whether the program is started from the project root or another directory.
CATALOG_PATH = Path(__file__).resolve().parent.parent / "reference_data" / "dmi-parameter-catalog.json"


class ExtractError(ValueError):
    """An input-data problem that should be reported to the caller."""

    pass


@dataclass(frozen=True)
class Station:
    """The identifying and location information shared by a weather station."""

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
    """The normalized result: unique stations plus all their observations."""

    stations: list[Station]
    observations: list[Observation]


def _require(mapping: Any, key: str, where: str) -> Any:
    # JSON objects become Python dictionaries. Check both the container and
    # field existence here so callers get a useful data error, not a KeyError
    # or TypeError later in the parsing process.
    if not isinstance(mapping, dict) or key not in mapping:
        raise ExtractError(f"{where}: missing field '{key}'")
    return mapping[key]


def _parse_timestamp(raw: Any, where: str) -> datetime:
    # Timestamps arrive as text in the JSON. Require a timezone because a
    # time such as 09:00 without a zone is ambiguous across locations.
    if not isinstance(raw, str):
        raise ExtractError(f"{where}: timestamp must be a string")
    try:
        # Python's ISO parser accepts "+00:00"; JSON APIs often write the same
        # UTC offset as "Z", so translate that suffix before parsing.
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ExtractError(f"{where}: invalid timestamp '{raw}'") from error
    if parsed.tzinfo is None:
        raise ExtractError(f"{where}: timestamp '{raw}' has no timezone")
    return parsed


def _parse_value(raw: Any, where: str) -> Decimal | None:
    # A missing measurement is represented explicitly as JSON null, which
    # Python reads as None. It is different from zero and is valid data.
    if raw is None:
        return None
    # bool is a subclass of int in Python, so reject True/False explicitly:
    # they describe truth values, not measured quantities.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ExtractError(f"{where}: value must be a number or null")
    # Decimal is preferable to binary floating point for measured values:
    # converting through str avoids importing the float's binary rounding
    # artifacts into the decimal representation.
    return Decimal(str(raw))


def _parse_station(feature: dict, where: str) -> Station:
    # Station fields are split between GeoJSON's "properties" and "geometry".
    properties = _require(feature, "properties", where)
    station_id = _require(properties, "stationId", where)
    coordinates = _require(_require(feature, "geometry", where), "coordinates", where)
    # GeoJSON coordinates must contain at least longitude and latitude, both
    # numeric. As above, booleans are technically numbers to Python but are
    # not meaningful geographic coordinates.
    if (
        not isinstance(station_id, str)
        or not isinstance(coordinates, list)
        or len(coordinates) < 2
        or not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in coordinates[:2])
    ):
        raise ExtractError(f"{where}: invalid stationId or coordinates")
    # GeoJSON order is [longitude, latitude].
    return Station(station_id, Decimal(str(coordinates[0])), Decimal(str(coordinates[1])))


def parse_observations(payload: Any) -> ParsedObservations:
    """Validate the input payload and convert its features into Python records.

    A payload contains a list of observation features. Many observations can
    refer to the same station, so this function returns stations separately
    (deduplicated by station ID) from the full observation list.
    """
    # First find the top-level feature list. Empty input is treated as an
    # error here rather than as a successful extraction of no data.
    features = _require(payload, "features", "payload")
    if not isinstance(features, list) or not features:
        raise ExtractError("payload: no observation features")

    # A dictionary gives us one station per station ID and makes it easy to
    # detect if the same ID is later associated with different coordinates.
    stations: dict[str, Station] = {}
    # Unlike stations, observations are not deduplicated: each feature is a
    # separate measurement and must be retained in the output.
    observations: list[Observation] = []

    # Process one feature at a time. "where" is included in errors so a bad
    # field can be traced back to its position in the input list.
    for index, feature in enumerate(features):
        where = f"feature[{index}]"
        properties = _require(feature, "properties", where)
        station = _parse_station(feature, where)

        # setdefault stores the station the first time we see its ID. If it
        # already exists, compare the newly parsed location with the original.
        known = stations.setdefault(station.station_id, station)
        if known != station:
            raise ExtractError(f"{where}: conflicting coordinates for station {station.station_id}")

        # These identifiers connect an observation to its measured parameter
        # and to the particular source record that supplied it.
        parameter_id = _require(properties, "parameterId", where)
        observation_id = _require(feature, "id", where)
        if not isinstance(parameter_id, str) or not isinstance(observation_id, str):
            raise ExtractError(f"{where}: id and parameterId must be strings")

        # Construct a normalized Observation. Each value is checked and
        # converted before it is stored, so later code can work with useful
        # Python types instead of repeatedly interpreting raw JSON.
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

    # Convert the station dictionary's values to a list for the public result.
    # The observations list still has one entry for every input feature.
    return ParsedObservations(list(stations.values()), observations)


def load_catalog(path: Path = CATALOG_PATH) -> dict:
    """Read and decode the JSON catalog that defines valid parameter IDs."""
    return json.loads(path.read_text(encoding="utf-8"))


def validate_parameters(observations: list[Observation], catalog: dict) -> None:
    """Fail if any observation uses a parameter absent from the catalog.

    The catalog is expected to have a "parameters" mapping whose keys are
    parameter IDs. Comparing sets checks all observations at once; the set
    removes duplicates, and sorting makes any error message deterministic.
    """
    known = catalog["parameters"]
    missing = sorted({o.parameter_id for o in observations} - set(known))
    if missing:
        raise ExtractError(f"parameters missing from catalog: {', '.join(missing)}")
