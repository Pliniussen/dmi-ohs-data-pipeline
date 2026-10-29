import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

from dmi_ohs.api import FetchError, fetch_observations
from dmi_ohs.database import get_connection
from dmi_ohs.extract_transform import (
    ExtractError,
    filter_known_parameters,
    load_catalog,
    parse_observations,
)
from dmi_ohs.load import LoadResult, latest_observed_at, load

# Re-fetch this much before the newest stored observation, to pick up rows
# that arrived late. The upserts make the overlap harmless.
OVERLAP = timedelta(hours=1)


class PipelineError(RuntimeError):
    """One or more stations could not be loaded."""

    pass


def warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def station_ids_from_env() -> list[str]:
    """Read the comma-separated DMI_STATION_IDS, e.g. "06120,06180".

    IDs stay text because the leading zero is part of the ID.
    """
    raw = os.environ.get("DMI_STATION_IDS", "06120")
    # dict.fromkeys drops repeated IDs but keeps the order they were given in.
    station_ids = list(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    if not station_ids:
        raise PipelineError("DMI_STATION_IDS contains no station IDs")
    return station_ids


def lookback_from_env() -> timedelta:
    """Read DMI_INITIAL_LOOKBACK_HOURS, a positive number of hours (default 24)."""
    raw = os.environ.get("DMI_INITIAL_LOOKBACK_HOURS", "24")
    try:
        hours = float(raw)
    except ValueError:
        hours = float("nan")
    # The comparison is false for NaN, so text and "nan" are rejected too.
    if not 0 < hours < float("inf"):
        raise PipelineError(f"DMI_INITIAL_LOOKBACK_HOURS must be a positive number, got '{raw}'")
    return timedelta(hours=hours)


def fetch_window(connection, station_id: str, lookback: timedelta, now: datetime) -> tuple[datetime, datetime]:
    """Continue from the newest stored observation, or look back from now if there is none."""
    latest = latest_observed_at(connection, station_id)
    start = latest - OVERLAP if latest is not None else now - lookback
    return start, now


def load_payload(connection, payload: dict, catalog: dict) -> LoadResult:
    """Parse, filter and load one payload, printing any warnings."""
    parsed = parse_observations(payload)
    for message in parsed.warnings:
        warn(message)
    kept, unknown = filter_known_parameters(parsed.observations, catalog)
    if unknown:
        warn(
            f"skipped {len(parsed.observations) - len(kept)} observations with parameters "
            f"missing from catalog: {', '.join(unknown)}"
        )

    result = load(connection, replace(parsed, observations=kept), catalog)
    for message in result.warnings:
        warn(message)
    return result


def describe(result: LoadResult) -> str:
    return (
        f"loaded {result.observations} observations, {result.stations} stations, "
        f"{result.parameters} parameters, {result.value_codes} value codes."
    )


def run_file(input_path: Path) -> LoadResult:
    """Load observations from a saved JSON file."""
    catalog = load_catalog()
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        # ValueError covers invalid JSON.
        raise PipelineError(f"{input_path}: {error}") from error
    connection = get_connection()
    try:
        result = load_payload(connection, payload, catalog)
    except ExtractError as error:
        raise PipelineError(f"{input_path}: {error}") from error
    finally:
        connection.close()
    print(f"{input_path.name}: {describe(result)}")
    return result


def run_api(fetch=fetch_observations) -> dict[str, LoadResult | None]:
    """Fetch and load new observations for every station in DMI_STATION_IDS.

    Each station is loaded in its own transaction, so a failing station does
    not stop the others. Returns each station's result, or None when the API
    had no new observations for it. Raises PipelineError afterwards if any
    station failed.
    """
    station_ids = station_ids_from_env()
    lookback = lookback_from_env()
    catalog = load_catalog()
    results: dict[str, LoadResult | None] = {}
    failed: list[str] = []

    connection = get_connection()
    try:
        for station_id in station_ids:
            try:
                start, end = fetch_window(connection, station_id, lookback, datetime.now(timezone.utc))
                payload = fetch(station_id, start, end)
                if not payload["features"]:
                    print(f"Station {station_id}: no new observations from {start} to {end}.")
                    results[station_id] = None
                    continue
                result = load_payload(connection, payload, catalog)
            # A database error has already rolled back this station's
            # transaction, so the connection can go on to the next station.
            except (FetchError, ExtractError, psycopg.Error) as error:
                warn(f"station {station_id} failed: {error}")
                failed.append(station_id)
                continue
            print(f"Station {station_id}: {describe(result)}")
            results[station_id] = result
    finally:
        connection.close()

    if failed:
        raise PipelineError(f"failed stations: {', '.join(failed)}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Load DMI observations into PostgreSQL.")
    parser.add_argument(
        "--file",
        type=Path,
        help="load a saved observation JSON file instead of fetching from the DMI API",
    )
    args = parser.parse_args()
    try:
        if args.file is None:
            run_api()
        else:
            run_file(args.file)
    except PipelineError as error:
        sys.exit(f"Error: {error}")


if __name__ == "__main__":
    main()
