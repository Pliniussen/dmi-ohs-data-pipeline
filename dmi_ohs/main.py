import json
import sys
from pathlib import Path

from dmi_ohs.database import get_connection
from dmi_ohs.extract_transform import load_catalog, parse_observations, validate_parameters
from dmi_ohs.load import load

DEFAULT_INPUT = Path(__file__).resolve().parent.parent / "sample_data" / "odense-observations-2026-10-07.json"


def run(input_path: Path = DEFAULT_INPUT):
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    parsed = parse_observations(payload)
    catalog = load_catalog()
    validate_parameters(parsed.observations, catalog)

    connection = get_connection()
    try:
        result = load(connection, parsed, catalog)
    finally:
        connection.close()

    print(
        f"Loaded {result.observations} observations, {result.stations} stations, "
        f"{result.parameters} parameters, {result.value_codes} value codes."
    )
    return result


def main():
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT)


if __name__ == "__main__":
    main()
