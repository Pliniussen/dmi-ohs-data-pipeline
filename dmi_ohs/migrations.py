from pathlib import Path

from dmi_ohs.database import get_connection


MIGRATIONS_PATH = Path(__file__).parent.parent / "database" / "migrations"


def run_migrations() -> None:
    migration_files = sorted(MIGRATIONS_PATH.glob("*.sql"))

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cursor.execute("SELECT version FROM schema_migrations")
            applied_versions = {row[0] for row in cursor.fetchall()}

            for migration_file in migration_files:
                version = migration_file.stem
                if version in applied_versions:
                    continue

                cursor.execute(migration_file.read_text(encoding="utf-8"))
                cursor.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
