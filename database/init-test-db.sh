#!/bin/sh
set -e

if [ "$TEST_POSTGRES_DB" = "$POSTGRES_DB" ]; then
    printf '%s\n' 'TEST_POSTGRES_DB must differ from POSTGRES_DB.' >&2
    exit 1
fi

createdb --username "$POSTGRES_USER" "$TEST_POSTGRES_DB"
psql --username "$POSTGRES_USER" --dbname "$TEST_POSTGRES_DB" \
    --set ON_ERROR_STOP=1 \
    --file /docker-entrypoint-initdb.d/001-schema.sql