from datetime import date
from decimal import Decimal

import psycopg
import pytest

from app.services.ledger import reconcile_ledger


DATABASE_URL = "postgresql://qdwork:qdwork@localhost:5432/qdwork"


CASES = [
    ("R003", "T926334", None, 25),
    ("R026", "T672899", None, 32),
    ("R033", None, date(2026, 9, 20), 176),
    ("R005", None, date(2026, 9, 21), 150),
    ("R014", None, date(2026, 9, 18), 10),
    ("R016", None, date(2026, 9, 19), 425),
    ("R034", None, date(2026, 9, 19), 249),
    ("R007", "T840677", None, 34),
    ("R031", "T312538", None, 22),
    ("R035", "T980582", None, 25),
    ("R024", None, date(2026, 9, 18), 150),
]

ZERO_CASES = [
    ("R008", "T252921", None),
    ("R013", None, None),
    ("R009", None, date(2026, 9, 17)),
    ("R025", None, date(2026, 9, 19)),
    ("R011", None, date(2026, 9, 19)),
]


def test_conversation_ledger_amounts():
    try:
        connection = psycopg.connect(DATABASE_URL)
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL test database unavailable: {error}")

    with connection:
        for rider_id, trip_id, payout_date, expected in CASES:
            result = reconcile_ledger(
                connection,
                rider_id,
                trip_id=trip_id,
                payout_date=payout_date,
            )
            assert result.difference == Decimal(expected)

        for rider_id, trip_id, payout_date in ZERO_CASES:
            result = reconcile_ledger(
                connection,
                rider_id,
                trip_id=trip_id,
                payout_date=payout_date,
            )
            assert result.difference == Decimal("0")
            print(
                f"{rider_id}: owed 0 - expected payout already reconciles with "
                f"payout_lines; paid={result.actual_total}, expected={result.expected_total}"
            )


def test_missing_trips_use_full_fares():
    try:
        connection = psycopg.connect(DATABASE_URL)
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL test database unavailable: {error}")

    with connection:
        r016 = reconcile_ledger(connection, "R016", payout_date=date(2026, 9, 19))
        r034 = reconcile_ledger(connection, "R034", payout_date=date(2026, 9, 19))

        assert r016.difference == Decimal("425")
        assert r034.difference == Decimal("249")
        assert all(
            finding.type.value == "missing_trip_pay"
            and finding.trip_id is not None
            and finding.amount > 0
            and finding.why
            and finding.details["requires_approval"] is True
            for finding in r016.findings + r034.findings
        )


def test_trip_belongs_to_another_rider_returns_nothing():
    try:
        connection = psycopg.connect(DATABASE_URL)
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL test database unavailable: {error}")

    with connection:
        result = reconcile_ledger(connection, "R003", trip_id="T672899")
        assert result.expected_total == Decimal("0")
        assert result.actual_total == Decimal("0")
        assert result.difference == Decimal("0")
        assert result.findings == []
