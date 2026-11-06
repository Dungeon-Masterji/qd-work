import csv
from pathlib import Path

import psycopg
import pytest

from app.db.seed import seed_if_empty


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_seed_tiny_csv_set():
    database_url = "postgresql://qdwork:qdwork@localhost:5432/qdwork"
    try:
        connection = psycopg.connect(database_url, autocommit=True)
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL test database unavailable: {error}")

    with connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS seed_test CASCADE")
            cursor.execute("CREATE SCHEMA seed_test")
            cursor.execute("SET search_path TO seed_test")
            cursor.execute(
                "CREATE TABLE riders (rider_id TEXT PRIMARY KEY, name TEXT NOT NULL, city TEXT NOT NULL, joined_on DATE NOT NULL)"
            )
            cursor.execute(
                """
                CREATE TABLE trips (
                    trip_id TEXT PRIMARY KEY, rider_id TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL,
                    status TEXT NOT NULL, distance_km NUMERIC NOT NULL, surge_multiplier NUMERIC NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE payout_lines (
                    line_id TEXT PRIMARY KEY, payout_date DATE NOT NULL, rider_id TEXT NOT NULL,
                    line_type TEXT NOT NULL, trip_id TEXT, amount NUMERIC NOT NULL
                )
                """
            )

        data_dir = Path("/tmp/qdwork-seed-test")
        data_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(
            data_dir / "riders.csv",
            ["rider_id", "name", "city", "joined_on"],
            [{"rider_id": "R001", "name": "Test Rider", "city": "Test City", "joined_on": "2026-01-01"}],
        )
        _write_csv(
            data_dir / "trips.csv",
            ["trip_id", "rider_id", "started_at", "status", "distance_km", "surge_multiplier"],
            [{"trip_id": "T1", "rider_id": "r1", "started_at": "2026-09-20T10:00:00Z", "status": "completed", "distance_km": "3.5", "surge_multiplier": "1.0"}],
        )
        _write_csv(
            data_dir / "payout_lines.csv",
            ["line_id", "payout_date", "rider_id", "line_type", "trip_id", "amount"],
            [{"line_id": "P1", "payout_date": "2026-09-20", "rider_id": "R1", "line_type": "trip", "trip_id": "T1", "amount": "25"}],
        )

        seed_if_empty(connection, data_dir)

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM riders")
            assert cursor.fetchone()[0] == 1
            cursor.execute("SELECT COUNT(*) FROM trips")
            assert cursor.fetchone()[0] == 1
            cursor.execute("SELECT COUNT(*) FROM payout_lines")
            assert cursor.fetchone()[0] == 1
