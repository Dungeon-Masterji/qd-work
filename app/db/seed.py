import csv
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg


DATA_DIR = Path(__file__).parents[2] / "data"
VALID_STATUSES = {"completed", "cancelled_by_rider", "cancelled_by_customer"}
logger = logging.getLogger(__name__)


def _parse_timestamp(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalize_rider_id(value: str) -> str:
    value = value.strip().upper()
    match = re.fullmatch(r"R(\d+)", value)
    return f"R{int(match.group(1)):03d}" if match else value


def seed_if_empty(connection: psycopg.Connection, data_dir: Path = DATA_DIR) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    riders_loaded = riders_skipped = 0
    trips_loaded = trips_skipped = trips_fixed = 0
    payout_lines_loaded = payout_lines_skipped = payout_lines_fixed = 0

    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM riders")
        rider_count = cursor.fetchone()[0]
        if rider_count == 0:
            with (data_dir / "riders.csv").open(newline="", encoding="utf-8") as file:
                riders = [
                    (row["rider_id"], row["name"], row["city"], row["joined_on"])
                    for row in csv.DictReader(file)
                ]
            cursor.executemany(
                """
                INSERT INTO riders (rider_id, name, city, joined_on)
                VALUES (%s, %s, %s, %s)
                """,
                riders,
            )
            riders_loaded = len(riders)
        counts["riders"] = {"loaded": riders_loaded, "skipped": riders_skipped, "fixed": 0}

        cursor.execute("SELECT COUNT(*) FROM trips")
        if cursor.fetchone()[0] == 0:
            cursor.execute("SELECT rider_id FROM riders")
            known_riders = {row[0] for row in cursor.fetchall()}
            trips = []
            seen_trip_ids = set()
            skipped = fixed = 0
            with (data_dir / "trips.csv").open(newline="", encoding="utf-8") as file:
                for row in csv.DictReader(file):
                    if row["trip_id"] in seen_trip_ids:
                        skipped += 1
                        continue
                    seen_trip_ids.add(row["trip_id"])

                    rider_id = _normalize_rider_id(row["rider_id"])
                    if rider_id != row["rider_id"].strip():
                        fixed += 1
                    if rider_id not in known_riders or row["status"] not in VALID_STATUSES:
                        skipped += 1
                        continue
                    try:
                        started_at = _parse_timestamp(row["started_at"])
                        if started_at.tzinfo is None:
                            started_at = started_at.replace(tzinfo=timezone.utc)
                            fixed += 1
                        distance = Decimal(row["distance_km"])
                    except (TypeError, ValueError, InvalidOperation):
                        skipped += 1
                        continue
                    if not row["distance_km"].strip():
                        skipped += 1
                        continue

                    trips.append((
                        row["trip_id"], rider_id, started_at, row["status"],
                        distance, row["surge_multiplier"],
                    ))
            cursor.executemany(
                """
                INSERT INTO trips (
                    trip_id, rider_id, started_at, status, distance_km, surge_multiplier
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                trips,
            )
            trips_loaded = len(trips)
            trips_skipped = skipped
            trips_fixed = fixed
        counts["trips"] = {
            "loaded": trips_loaded, "skipped": trips_skipped, "fixed": trips_fixed,
        }

        cursor.execute("SELECT COUNT(*) FROM payout_lines")
        if cursor.fetchone()[0] == 0:
            cursor.execute("SELECT trip_id FROM trips")
            known_trips = {row[0] for row in cursor.fetchall()}
            payout_lines = []
            skipped = fixed = 0
            with (data_dir / "payout_lines.csv").open(newline="", encoding="utf-8") as file:
                for row in csv.DictReader(file):
                    rider_id = _normalize_rider_id(row["rider_id"])
                    if rider_id != row["rider_id"].strip():
                        fixed += 1
                    trip_id = row["trip_id"] or None
                    if trip_id and trip_id not in known_trips:
                        skipped += 1
                        continue
                    try:
                        amount = Decimal(row["amount"])
                        if row["line_type"] == "penalty" and amount > 0:
                            amount = -amount
                            fixed += 1
                    except (TypeError, ValueError, InvalidOperation):
                        skipped += 1
                        continue
                    payout_lines.append((
                        row["line_id"], row["payout_date"], rider_id, row["line_type"],
                        trip_id, amount,
                    ))
            cursor.executemany(
                """
                INSERT INTO payout_lines (
                    line_id, payout_date, rider_id, line_type, trip_id, amount
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                payout_lines,
            )
            payout_lines_loaded = len(payout_lines)
            payout_lines_skipped = skipped
            payout_lines_fixed = fixed

            cursor.execute(
                """
                UPDATE trips AS t
                SET distance_km = (p.amount - 25) / 6 + 2
                FROM (
                    SELECT DISTINCT ON (trip_id) trip_id, amount
                    FROM payout_lines
                    WHERE line_type = 'trip' AND trip_id IS NOT NULL
                    ORDER BY trip_id, line_id
                ) AS p
                WHERE t.trip_id = p.trip_id
                  AND t.distance_km > 100
                  AND p.amount BETWEEN 25 AND 100
                  AND (p.amount - 25) / 6 + 2 <= 100
                """
            )
        counts["payout_lines"] = {
            "loaded": payout_lines_loaded,
            "skipped": payout_lines_skipped,
            "fixed": payout_lines_fixed,
        }

    for table, table_counts in counts.items():
        logger.info(
            "seed %s: loaded=%d skipped=%d fixed=%d",
            table, table_counts["loaded"], table_counts["skipped"], table_counts["fixed"],
        )
    return counts
