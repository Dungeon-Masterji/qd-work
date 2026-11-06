from decimal import Decimal

from pydantic import BaseModel

from app.models.finding import Finding


class LedgerResult(BaseModel):
    rider_id: str
    expected_total: Decimal
    actual_total: Decimal
    difference: Decimal
    findings: list[Finding] = []
    per_trip: dict[str, dict[str, Decimal]] = {}
    per_day: dict[str, dict[str, Decimal]] = {}
