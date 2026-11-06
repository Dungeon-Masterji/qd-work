import os
from pathlib import Path

import psycopg


MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def run_migrations() -> None:
    database_url = os.environ["DATABASE_URL"]

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cursor.execute("SELECT filename FROM schema_migrations")
            applied = {row[0] for row in cursor.fetchall()}

            for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if migration.name in applied:
                    continue

                cursor.execute(migration.read_text())
                cursor.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)",
                    (migration.name,),
                )