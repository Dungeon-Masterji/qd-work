from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.models import Finding, FindingType
from app.services.payswift import PaySwiftClient, PaySwiftError


FINDINGS = [
    Finding(
        type=FindingType.MISSING_SURGE,
        trip_id="T926334",
        amount=Decimal("25"),
        why="Missing surge",
    )
]


def key_from_request(request: httpx.Request) -> str:
    return request.headers["Idempotency-Key"]


@pytest.mark.asyncio
async def test_429_then_201(monkeypatch):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(201, json={"payout_id": "P1", "status": "created"})

    async def no_sleep(_):
        return None

    monkeypatch.setattr("app.services.payswift.asyncio.sleep", no_sleep)
    client = PaySwiftClient(
        "http://payswift.test",
        transport=httpx.MockTransport(handler),
    )
    result = await client.payout(
        "R003", date(2026, 9, 20), FINDINGS, 25, "test"
    )
    assert result["payout_id"] == "P1"
    assert calls == 2


@pytest.mark.asyncio
async def test_500_then_201_same_key(monkeypatch):
    keys = []

    async def handler(request: httpx.Request) -> httpx.Response:
        keys.append(key_from_request(request))
        if len(keys) == 1:
            return httpx.Response(500)
        return httpx.Response(201, json={"payout_id": "P2", "status": "created"})

    async def no_sleep(_):
        return None

    monkeypatch.setattr("app.services.payswift.asyncio.sleep", no_sleep)
    client = PaySwiftClient(
        "http://payswift.test",
        transport=httpx.MockTransport(handler),
    )
    await client.payout("R003", date(2026, 9, 20), FINDINGS, 25, "test")
    assert len(keys) == 2
    assert keys[0] == keys[1]


@pytest.mark.asyncio
async def test_timeout_then_found_in_list(monkeypatch):
    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.method == "POST":
            posts += 1
            raise httpx.ReadTimeout("timeout", request=request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[{"payout_id": "P3", "status": "created", "reference": "test"}],
            )
        raise AssertionError("unexpected request")

    async def no_sleep(_):
        return None

    monkeypatch.setattr("app.services.payswift.asyncio.sleep", no_sleep)
    client = PaySwiftClient(
        "http://payswift.test",
        transport=httpx.MockTransport(handler),
    )
    result = await client.payout("R003", date(2026, 9, 20), FINDINGS, 25, "test")
    assert result["payout_id"] == "P3"
    assert posts == 1


@pytest.mark.asyncio
async def test_409_uses_matching_payout():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(409)
        return httpx.Response(
            200,
            json=[{"payout_id": "P4", "status": "created", "reference": "test"}],
        )

    client = PaySwiftClient(
        "http://payswift.test",
        transport=httpx.MockTransport(handler),
    )
    result = await client.payout("R003", date(2026, 9, 20), FINDINGS, 25, "test")
    assert result["payout_id"] == "P4"


@pytest.mark.asyncio
async def test_400_fails_clearly():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="invalid amount")

    client = PaySwiftClient(
        "http://payswift.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(PaySwiftError, match="PaySwift rejected payout"):
        await client.payout("R003", date(2026, 9, 20), FINDINGS, 25, "test")
