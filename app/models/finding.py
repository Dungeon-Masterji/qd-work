from datetime import date as Date
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel


class FindingType(str, Enum):
    MISSING_TRIP_PAY = "missing_trip_pay"
    MISSING_SURGE = "missing_surge"
    WRONG_DISTANCE_PAY = "wrong_distance_pay"
    MISSING_INCENTIVE = "missing_incentive"
    DOUBLE_PENALTY = "double_penalty"
    WRONGLY_CHARGED_PENALTY = "wrongly_charged_penalty"


class Finding(BaseModel):
    type: FindingType
    trip_id: str | None = None
    date: Date | None = None
    amount: Decimal
    why: str
    expected: Decimal | None = None
    actual: Decimal | None = None
    difference: Decimal | None = None
    details: dict[str, Any] = {}
