from datetime import date as Date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class IntentIssueType(str, Enum):
    MISSING_SURGE = "missing_surge"
    MISSING_TRIP_PAYMENT = "missing_trip_payment"
    WRONG_DISTANCE_PAY = "wrong_distance_pay"
    MISSING_INCENTIVE = "missing_incentive"
    CANCEL_PENALTY = "cancel_penalty"
    PAYOUT_WRONG_VAGUE = "payout_wrong_vague"


class IntentIssue(BaseModel):
    type: IntentIssueType
    trip_id: str | None = None
    date: Date | None = None
    claimed_amount: Decimal | None = Field(default=None, ge=0)
    claimed_trip_count: int | None = Field(default=None, ge=0)


class IntentMessageKind(str, Enum):
    NEW_DISPUTE = "new_dispute"
    FOLLOWUP_ANSWER = "followup_answer"
    DISAGREEMENT = "disagreement"
    STATUS_QUESTION = "status_question"
    THANKS_OR_ACK = "thanks_or_ack"
    OTHER = "other"


class IntentLanguage(str, Enum):
    HINGLISH = "hinglish"
    ENGLISH = "english"


class IntentOutput(BaseModel):
    issues: list[IntentIssue] = Field(default_factory=list)
    message_kind: IntentMessageKind = IntentMessageKind.NEW_DISPUTE
    language: IntentLanguage = IntentLanguage.HINGLISH
    needs_clarification: bool = False
    clarification_question: str | None = None
    suspicious: bool = False
    suspicious_reason: str | None = None
    wants_human: bool = False
    human_reason: str | None = None
