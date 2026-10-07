# DMI OHS Pipeline Summary

## Extraction flow

1. Discover or select a DMI `stationId`.
2. Fetch observations from the DMI observation API using the station ID and time range.
3. Fetch station metadata from the DMI station API using the same station ID.
4. Extract distinct `parameterId` values from the observation response.
5. Look up those IDs in `data/dmi-parameter-catalog.json`.
6. Load station metadata, parameter metadata, code mappings, and observations into PostgreSQL.
7. Report an error for any observed parameter missing from the catalog instead of inserting incomplete metadata.

The parameter catalog is local reference data derived from DMI documentation. It supplies metadata not included in the observation API, including units, frequencies, descriptions, and coded-value descriptions. All catalog descriptions use arrays of paragraphs so the loader can consistently use `"\n\n".join(description)`.

## Proposed database schema

### `stations`

Stores station metadata from the station API. The DMI `stationId` identifies a station, but the API may return multiple historical records for one station. Preserve those records with validity fields such as `valid_from` and `valid_to` rather than assuming one row per station ID.

Important fields: `station_id`, `name`, `geometry` or latitude/longitude, `country`, `type`, `status`, `operation_from`, `operation_to`, `valid_from`, `valid_to`, and the raw API feature ID.

### `parameters`

Stores the catalog metadata keyed by `parameter_id`.

Important fields: `parameter_id` (primary key), `unit`, `frequency`, and `description`.

### `parameter_codes`

Stores documented coded values separately from parameter metadata.

Important fields: `parameter_id`, `code`, and `description`, with a primary key on `(parameter_id, code)`. This includes values such as precipitation `-0.1`, snow depth `-1`, cloud-cover codes, wind-direction code `0`, and weather codes.

### `observations`

Uses long format: one row per station, parameter, observation timestamp, and value.

Important fields: source observation ID, `station_id`, `parameter_id`, `observed_at`, `created_at`, numeric `value`, and coordinates if they are retained from the observation feature. Add a uniqueness constraint on the source observation ID, or on the natural key if the API does not provide a stable ID.

## Relationships

```text
stations 1 ---- * observations * ---- 1 parameters
parameters 1 ---- * parameter_codes
```

The database structure is fixed. New stations, parameters, codes, and observations are inserted or upserted as rows; the schema is not changed dynamically.

## Current reference data

- `data/dmi-parameter-catalog.json` contains the DMI-documented parameter metadata and code mappings.
- `data/odense-observations-2026-10-07.json` contains a saved observation sample for station `06120`.
- `data/odense-station.json` contains saved station metadata for station `06120`.
- The raw API files are strict JSON; extraction commands are kept in separate `.command.txt` files.

Source documentation: https://www.dmi.dk/friedata/dokumentation/meteorological-observations-data
