from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


ReplyOutcome = Literal[
    "paid",
    "partial",
    "nothing_owed",
    "already_paid",
    "need_info",
    "escalated",
    "not_your_account",
]


class ReplyDecision(BaseModel):
    outcome: ReplyOutcome
    language: Literal["hinglish", "english"] = "hinglish"
    amounts: dict[str, Decimal] = Field(default_factory=dict)
    trip_ids: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
