from decimal import Decimal

import pytest

from app.models import ReplyDecision
from app.services.llm import LLMProvider
from app.services.replies import template_reply, write_reply


class StaticReplyProvider(LLMProvider):
    def __init__(self, reply):
        self.reply = reply

    async def complete_json(self, prompt, *, system_prompt=None):
        return {"reply": self.reply}


@pytest.mark.asyncio
async def test_made_up_amount_is_replaced():
    decision = ReplyDecision(
        outcome="paid",
        language="hinglish",
        amounts={"paid": Decimal("25")},
        trip_ids=["T926334"],
    )
    reply = await write_reply(
        StaticReplyProvider("T926334 ka ₹999 payout bhej diya."),
        decision,
    )
    assert reply == template_reply(decision)


@pytest.mark.asyncio
async def test_template_reply_outcomes():
    paid = ReplyDecision(
        outcome="paid",
        amounts={"paid": Decimal("25")},
        trip_ids=["T926334"],
    )
    partial = ReplyDecision(
        outcome="partial",
        amounts={"paid": Decimal("15"), "approval": Decimal("10")},
    )
    assert "25 rupees" in template_reply(paid)
    assert "15 rupees" in template_reply(partial)
    assert "10 rupees" in template_reply(partial)
