from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


ONE_RUPEE = Decimal("1")
BASE_FARE = Decimal("25")
FIRST_PAID_KILOMETERS = Decimal("2")
DISTANCE_RATE = Decimal("6")
IST = ZoneInfo("Asia/Kolkata")


def _decimal(value: Decimal | int | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def fare(
    distance_km: Decimal | int | str,
    surge: Decimal | int | str | None = None,
) -> Decimal:
    distance = _decimal(distance_km)
    surge_multiplier = Decimal("1") if surge is None else _decimal(surge)
    extra_distance = max(distance - FIRST_PAID_KILOMETERS, Decimal("0"))
    fare_before_surge = BASE_FARE + DISTANCE_RATE * extra_distance
    return (fare_before_surge * surge_multiplier).quantize(
        ONE_RUPEE, rounding=ROUND_HALF_UP
    )


def day_ist(ts: datetime) -> date:
    return ts.astimezone(IST).date()


def in_window(trip_date: date, received_at: datetime) -> bool:
    received_date = day_ist(received_at)
    return received_date - timedelta(days=7) <= trip_date <= received_date


def incentive(completed_trip_count: int) -> Decimal:
    return Decimal("150") if completed_trip_count >= 12 else Decimal("0")


def cancel_penalty(status: str) -> Decimal:
    if status == "cancelled_by_rider":
        return Decimal("-10")
    if status == "cancelled_by_customer":
        return Decimal("0")
    return Decimal("0")
