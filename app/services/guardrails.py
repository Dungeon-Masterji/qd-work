import os
from datetime import date, datetime
from decimal import Decimal, ROUND_DOWN
from zoneinfo import ZoneInfo

from app.models import Finding, LedgerResult
from app.services.payswift import PaySwiftClient


AUTO_PAY_LIMIT = Decimal("200")
IST = ZoneInfo("Asia/Kolkata")


def _whole_owed(findings: list[Finding]) -> Decimal:
    owed = sum(
        (finding.amount for finding in findings if finding.amount > 0),
        Decimal("0"),
    )
    return owed.quantize(Decimal("1"), rounding=ROUND_DOWN)


def _owed_findings(findings: list[Finding]) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.amount > 0
        and (finding.difference is None or finding.difference > 0)
    ]


async def decide(
    rider_id: str,
    findings: list[Finding],
    today: date | datetime,
    *,
    payswift: PaySwiftClient | None = None,
    ledger: LedgerResult | None = None,
) -> tuple[int, int]:
    active_findings = _owed_findings(
        ledger.findings if ledger is not None else findings
    )
    owed = _whole_owed(active_findings)
    if ledger is not None:
        ledger_owed = ledger.difference.quantize(
            Decimal("1"),
            rounding=ROUND_DOWN,
        )
        owed = min(owed, max(ledger_owed, Decimal("0")))
    if owed <= 0:
        return 0, 0

    payswift = payswift or PaySwiftClient(
        os.environ.get("PAYSWIFT_BASE_URL", "http://localhost:8081")
    )
    today_datetime = (
        today
        if isinstance(today, datetime)
        else datetime.combine(today, datetime.min.time(), tzinfo=IST)
    )
    existing_today = await payswift.payouts_today_ist(
        rider_id,
        now=today_datetime,
    )

    if existing_today:
        return 0, int(owed)

    if owed > AUTO_PAY_LIMIT:
        return 0, int(owed)

    if len(active_findings) > 1 and ledger is None:
        first_finding = active_findings[0]
        first_finding_amount = first_finding.amount.quantize(
            Decimal("1"),
            rounding=ROUND_DOWN,
        )
        auto_pay = min(first_finding_amount, owed, AUTO_PAY_LIMIT)
    else:
        auto_pay = min(owed, AUTO_PAY_LIMIT)
    approval = owed - auto_pay
    return int(auto_pay), int(approval)
