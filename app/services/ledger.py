from datetime import date
from decimal import Decimal
from typing import Any

import psycopg

from app.models import Finding, FindingType, LedgerResult
from app.services.policy import cancel_penalty, day_ist, fare, incentive


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def reconcile_ledger(
    connection: psycopg.Connection,
    rider_id: str,
    *,
    trip_id: str | None = None,
    payout_date: date | None = None,
) -> LedgerResult:
    with connection.cursor() as cursor:
        trip_query = """
            SELECT trip_id, started_at, status, distance_km, surge_multiplier
            FROM trips
            WHERE rider_id = %s
        """
        params: list[Any] = [rider_id]

        if trip_id is not None:
            trip_query += " AND trip_id = %s"
            params.append(trip_id)

        trip_query += " ORDER BY started_at, trip_id"
        cursor.execute(trip_query, params)
        trips = cursor.fetchall()

    if trip_id is None and payout_date is not None:
        trips = [trip for trip in trips if day_ist(trip[1]) == payout_date]

    expected_by_trip: dict[str, Decimal] = {}
    completed_by_day: dict[date, int] = {}

    for current_trip_id, started_at, status, distance_km, surge_multiplier in trips:
        trip_day = day_ist(started_at)
        if status == "completed":
            expected_by_trip[current_trip_id] = fare(distance_km, surge_multiplier)
            completed_by_day[trip_day] = completed_by_day.get(trip_day, 0) + 1
        else:
            expected_by_trip[current_trip_id] = cancel_penalty(status)

    affected_days = {day_ist(trip[1]) for trip in trips}

    if payout_date is not None and trip_id is None:
        affected_days = {payout_date}

    if trip_id is not None and trips:
        affected_days = {day_ist(trips[0][1])}

    paid_by_trip: dict[str, Decimal] = {current_trip_id: Decimal("0") for current_trip_id in expected_by_trip}
    paid_by_day = {affected_day: Decimal("0") for affected_day in affected_days}

    if not affected_days:
        return LedgerResult(
            rider_id=rider_id,
            expected_total=Decimal("0"),
            actual_total=Decimal("0"),
            difference=Decimal("0"),
        )

    placeholders = ",".join(["%s"] * len(affected_days))
    day_params: list[Any] = [rider_id, *sorted(affected_days)]
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trip_id, amount
            FROM payout_lines
            WHERE rider_id = %s
              AND trip_id IS NOT NULL
              AND payout_date IN (
            """
            + placeholders
            + """
              )
            """,
            day_params,
        )
        for paid_trip_id, amount in cursor.fetchall():
            if paid_trip_id in paid_by_trip:
                paid_by_trip[paid_trip_id] += _decimal(amount)

        day_placeholders = ",".join(["%s"] * len(affected_days))
        cursor.execute(
            """
            SELECT payout_date, amount
            FROM payout_lines
            WHERE rider_id = %s AND payout_date IN (
            """
            + day_placeholders
            + """
              )
            """,
            [rider_id, *sorted(affected_days)],
        )
        for paid_day, amount in cursor.fetchall():
            paid_by_day[paid_day] += _decimal(amount)

    expected_by_day = {affected_day: Decimal("0") for affected_day in affected_days}
    for current_trip_id, started_at, status, distance_km, surge_multiplier in trips:
        trip_day = day_ist(started_at)
        if status == "completed":
            expected_by_day[trip_day] += fare(distance_km, surge_multiplier)
        else:
            expected_by_day[trip_day] += cancel_penalty(status)

    for affected_day in affected_days:
        if trip_id is None or affected_day == day_ist(trips[0][1]):
            completed_count = completed_by_day.get(affected_day, 0)
            expected_by_day[affected_day] += incentive(completed_count)

    per_trip = {
        current_trip_id: {
            "expected": expected,
            "paid": paid_by_trip[current_trip_id],
        }
        for current_trip_id, expected in expected_by_trip.items()
    }
    per_day = {
        str(current_day): {
            "expected": expected_by_day[current_day],
            "paid": paid_by_day[current_day],
        }
        for current_day in sorted(affected_days)
    }
    expected_total = sum(expected_by_day.values(), Decimal("0"))
    actual_total = sum(paid_by_day.values(), Decimal("0"))

    findings: list[Finding] = []
    if trip_id is not None:
        expected_total = sum(
            (amounts["expected"] for amounts in per_trip.values()), Decimal("0")
        )
        actual_total = sum(
            (amounts["paid"] for amounts in per_trip.values()), Decimal("0")
        )

        for current_trip_id, amounts in per_trip.items():
            owed = amounts["expected"] - amounts["paid"]
            if owed > 0:
                findings.append(
                    Finding(
                        type=FindingType.MISSING_SURGE if amounts["paid"] > 0 else FindingType.MISSING_TRIP_PAY,
                        trip_id=current_trip_id,
                        amount=owed,
                        why=f"Trip {current_trip_id} was paid {amounts['paid']} rupees, but policy fare is {amounts['expected']} rupees.",
                        expected=amounts["expected"],
                        actual=amounts["paid"],
                        difference=owed,
                    )
                )
    else:
        missing_trip_totals = {
            affected_day: sum(
                (
                    fare(trip[3], trip[4])
                    for trip in trips
                    if trip[2] == "completed"
                    and day_ist(trip[1]) == affected_day
                    and paid_by_trip[trip[0]] == Decimal("0")
                ),
                Decimal("0"),
            )
            for affected_day in affected_days
        }
        for current_trip_id, started_at, status, distance_km, surge_multiplier in trips:
            if status != "completed":
                continue
            if paid_by_trip[current_trip_id] == Decimal("0"):
                owed = fare(distance_km, surge_multiplier)
                findings.append(
                    Finding(
                        type=FindingType.MISSING_TRIP_PAY,
                        trip_id=current_trip_id,
                        amount=owed,
                        why=f"Trip {current_trip_id} has no payout line; the full policy fare of {owed} rupees is owed.",
                        expected=owed,
                        actual=Decimal("0"),
                        difference=owed,
                        details={
                            "requires_approval": missing_trip_totals[day_ist(started_at)] > 200
                        },
                    )
                )

        for affected_day in affected_days:
            owed = expected_by_day[affected_day] - paid_by_day[affected_day]
            missing_trip_total = sum(
                (
                    finding.amount
                    for finding in findings
                    if finding.date == affected_day
                    or (
                        finding.trip_id is not None
                        and any(
                            trip[0] == finding.trip_id
                            and day_ist(trip[1]) == affected_day
                            for trip in trips
                        )
                    )
                ),
                Decimal("0"),
            )
            incentive_owed = owed - missing_trip_total
            if incentive_owed > 0:
                findings.append(
                    Finding(
                        type=FindingType.MISSING_INCENTIVE,
                        date=affected_day,
                        amount=owed - missing_trip_total,
                        why=f"Payout for {affected_day.isoformat()} is {paid_by_day[affected_day]} rupees; policy requires {expected_by_day[affected_day]} rupees.",
                        expected=expected_by_day[affected_day],
                        actual=paid_by_day[affected_day],
                        difference=owed,
                    )
                )

    return LedgerResult(
        rider_id=rider_id,
        expected_total=expected_total,
        actual_total=actual_total,
        difference=expected_total - actual_total,
        per_trip=per_trip,
        per_day=per_day,
        findings=findings,
    )
