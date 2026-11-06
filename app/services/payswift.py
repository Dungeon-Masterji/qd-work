import asyncio
import hashlib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Iterable
from zoneinfo import ZoneInfo

import httpx

from app.models import Finding


MAX_ATTEMPTS = 6
MIN_RETRY_DELAY_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 30.0
RATE_LIMIT_DELAY_SECONDS = 5.0
IST = ZoneInfo("Asia/Kolkata")


def idempotency_key(rider_id: str, payout_date: date, findings: Iterable[Finding]) -> str:
    finding_ids = sorted(
        finding.trip_id or finding.date.isoformat()
        for finding in findings
        if finding.trip_id is not None or finding.date is not None
    )
    material = f"{rider_id}:{payout_date.isoformat()}:{','.join(finding_ids)}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"payout:{rider_id}:{payout_date.isoformat()}:{digest[:16]}"


class PaySwiftError(RuntimeError):
    pass


class PaySwiftClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    async def _post_with_retries(
        self,
        client: httpx.AsyncClient,
        key: str,
        payload: dict[str, object],
    ) -> httpx.Response:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await client.post(
                    f"{self.base_url}/v1/payouts",
                    headers={"Idempotency-Key": key},
                    json=payload,
                )
            except httpx.TimeoutException:
                payouts = await self.list_payouts(
                    str(payload["rider_id"]),
                    client=client,
                )
                for payout in payouts:
                    if payout.get("reference") == payload["reference"]:
                        return httpx.Response(
                            201,
                            json=payout,
                            request=httpx.Request("POST", f"{self.base_url}/v1/payouts"),
                        )
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(
                    min(MIN_RETRY_DELAY_SECONDS * (2**attempt), MAX_RETRY_DELAY_SECONDS)
                )
                continue

            if response.status_code == 400:
                raise PaySwiftError(
                    f"PaySwift rejected payout (400): {response.text}"
                )
            if response.status_code == 409:
                return response
            if response.status_code < 500 and response.status_code != 429:
                response.raise_for_status()
                return response

            if attempt == MAX_ATTEMPTS - 1:
                response.raise_for_status()

            delay = min(MIN_RETRY_DELAY_SECONDS * (2**attempt), MAX_RETRY_DELAY_SECONDS)
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None and response.status_code == 429:
                try:
                    delay = int(
                        Decimal(retry_after).to_integral_value(rounding=ROUND_CEILING)
                    )
                except (ValueError, InvalidOperation):
                    pass
            elif response.status_code == 429:
                delay = RATE_LIMIT_DELAY_SECONDS
            await asyncio.sleep(delay)

        raise PaySwiftError("PaySwift request exhausted retries")

    async def list_payouts(
        self,
        rider_id: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> list[dict[str, object]]:
        async def request(active_client: httpx.AsyncClient) -> list[dict[str, object]]:
            response = await active_client.get(
                f"{self.base_url}/v1/payouts",
                params={"rider_id": rider_id} if rider_id is not None else None,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                return payload["data"]
            raise PaySwiftError("PaySwift returned an invalid payouts response")

        if client is not None:
            return await request(client)
        async with httpx.AsyncClient(
            timeout=self.timeout,
            transport=self.transport,
        ) as active_client:
            return await request(active_client)

    async def payouts_today_ist(
        self,
        rider_id: str,
        *,
        now: datetime | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> list[dict[str, object]]:
        today = (now or datetime.now(IST)).astimezone(IST).date()
        results = []
        for payout in await self.list_payouts(rider_id, client=client):
            created_at = payout.get("created_at")
            if not isinstance(created_at, str):
                continue
            parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if parsed.astimezone(IST).date() == today:
                results.append(payout)
        return results

    async def payout(
        self,
        rider_id: str,
        payout_date: date,
        findings: Iterable[Finding],
        amount: Decimal | int,
        reference: str,
    ) -> dict[str, object]:
        try:
            rupees = Decimal(str(amount))
        except InvalidOperation as error:
            raise ValueError("PaySwift amount must be a whole rupee amount") from error

        if rupees != rupees.to_integral_value() or rupees < 1 or rupees > 10000:
            raise ValueError("PaySwift amount must be an integer from 1 to 10000")

        finding_list = list(findings)
        key = idempotency_key(rider_id, payout_date, finding_list)
        payload = {
            "rider_id": rider_id,
            "amount": int(rupees),
            "reference": reference,
        }

        async with httpx.AsyncClient(
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            response = await self._post_with_retries(client, key, payload)

            if response.status_code == 409:
                lookup = await client.get(
                    f"{self.base_url}/v1/payouts",
                    params={"rider_id": rider_id},
                )
                lookup.raise_for_status()
                payouts = lookup.json()
                for payout in payouts:
                    if payout.get("reference") == reference:
                        return payout
                raise PaySwiftError(
                    "PaySwift returned 409, but no matching payout was found"
                )

            response.raise_for_status()
            return response.json()
