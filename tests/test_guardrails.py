from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.models import Finding, FindingType, LedgerResult
from app.services.guardrails import decide
from app.services.payswift import PaySwiftClient


def finding(amount: str) -> Finding:
    return Finding(
        type=FindingType.MISSING_SURGE,
        trip_id="T926334",
        amount=Decimal(amount),
        why="Missing payout",
    )


@pytest.mark.asyncio
async def test_guardrails_cap_and_approval():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    payswift = PaySwiftClient(
        "http://payswift.test",
        transport=httpx.MockTransport(handler),
    )
    auto_pay, approval = await decide(
        "R003", [finding("425")], date(2026, 9, 20), payswift=payswift
    )
    assert (auto_pay, approval) == (0, 425)


@pytest.mark.asyncio
async def test_guardrails_existing_payswift_payout_routes_all_to_approval():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "payout_id": "P1",
                        "created_at": "2026-09-20T09:00:00+05:30",
                        "status": "processed",
                        "amount": 25,
                    }
                ]
            },
        )

    payswift = PaySwiftClient(
        "http://payswift.test",
        transport=httpx.MockTransport(handler),
    )
    auto_pay, approval = await decide(
        "R003", [finding("100")], date(2026, 9, 20), payswift=payswift
    )
    assert (auto_pay, approval) == (0, 100)


@pytest.mark.asyncio
async def test_two_findings_pay_one_and_approve_the_other():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    payswift = PaySwiftClient(
        "http://payswift.test",
        transport=httpx.MockTransport(handler),
    )
    findings = [finding("15"), finding("10")]
    auto_pay, approval = await decide(
        "R027", findings, date(2026, 9, 23), payswift=payswift
    )
    assert (auto_pay, approval) == (15, 10)


@pytest.mark.asyncio
async def test_guardrails_caps_claim_at_ledger_owed():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    payswift = PaySwiftClient(
        "http://payswift.test",
        transport=httpx.MockTransport(handler),
    )
    ledger = LedgerResult(
        rider_id="R035",
        expected_total=Decimal("25"),
        actual_total=Decimal("0"),
        difference=Decimal("25"),
        findings=[finding("25")],
    )
    auto_pay, approval = await decide(
        "R035",
        [finding("300")],
        date(2026, 9, 23),
        payswift=payswift,
        ledger=ledger,
    )
    assert (auto_pay, approval) == (25, 0)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (200, (200, 0)),
        (201, (0, 201)),
        (249, (0, 249)),
    ],
)
@pytest.mark.asyncio
async def test_auto_pay_boundary(amount, expected):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    payswift = PaySwiftClient(
        "http://payswift.test",
        transport=httpx.MockTransport(handler),
    )
    auto_pay, approval = await decide(
        "R003",
        [finding(str(amount))],
        date(2026, 9, 23),
        payswift=payswift,
    )
    assert (auto_pay, approval) == expected


@pytest.mark.asyncio
async def test_zero_owed_skips_settled_finding():
    settled = Finding(
        type=FindingType.MISSING_SURGE,
        trip_id="T926334",
        amount=Decimal("25"),
        difference=Decimal("0"),
        why="Already settled",
    )
    auto_pay, approval = await decide(
        "R003",
        [settled],
        date(2026, 9, 23),
    )
    assert (auto_pay, approval) == (0, 0)
