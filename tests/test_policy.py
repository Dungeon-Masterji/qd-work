from decimal import Decimal
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.services.policy import cancel_penalty, day_ist, fare, incentive, in_window


def test_fare_under_two_kilometers():
    assert fare(Decimal("1.5")) == Decimal("25")


def test_fare_at_exactly_two_kilometers():
    assert fare(Decimal("2")) == Decimal("25")


def test_fare_rounds_down_at_7_4_kilometers():
    assert fare(Decimal("7.4")) == Decimal("57")


def test_fare_surge_rounds_half_up():
    assert fare(Decimal("3"), Decimal("1.5")) == Decimal("47")


def test_fare_defaults_surge_to_one():
    assert fare(Decimal("7.4"), None) == Decimal("57")


def test_day_ist_crosses_date_at_23_50_utc():
    ts = datetime(2026, 9, 20, 23, 50, tzinfo=timezone.utc)
    assert day_ist(ts).isoformat() == "2026-09-21"


def test_day_ist_at_00_10_ist():
    ts = datetime(2026, 9, 20, 0, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert day_ist(ts).isoformat() == "2026-09-20"


def test_day_ist_separates_utc_evening_from_ist_midnight():
    utc_evening = datetime(2026, 9, 20, 23, 50, tzinfo=timezone.utc)
    ist_midnight = datetime(2026, 9, 20, 0, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert (day_ist(utc_evening), day_ist(ist_midnight)) == (
        date(2026, 9, 21),
        date(2026, 9, 20),
    )


def test_incentive_requires_twelve_completed_trips():
    assert incentive(11) == Decimal("0")
    assert incentive(12) == Decimal("150")


def test_cancel_penalties():
    assert cancel_penalty("cancelled_by_rider") == Decimal("-10")
    assert cancel_penalty("cancelled_by_customer") == Decimal("0")


def test_in_window_includes_boundary_day():
    received_at = datetime(2026, 9, 20, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    assert in_window(date(2026, 9, 13), received_at)
    assert not in_window(date(2026, 9, 12), received_at)
