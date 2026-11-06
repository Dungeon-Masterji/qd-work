import re

from app.models import ReplyDecision
from app.services.llm import LLMProvider
from app.services.prompts import REPLY_WRITER_SYSTEM


def template_reply(decision: ReplyDecision) -> str:
    amounts = decision.amounts
    paid = format_amount(amounts.get("paid", 0))
    expected = format_amount(amounts.get("owed", 0))
    approval = format_amount(amounts.get("approval", 0))
    trip = decision.trip_ids[0] if decision.trip_ids else None
    trip_text = f" order {trip}" if trip else ""

    if decision.outcome == "paid":
        return (
            f"{paid} rupees ka payout process kar diya hai{trip_text}."
            if decision.language == "hinglish"
            else f"{paid} rupees payout has been processed{trip_text}."
        )
    if decision.outcome == "partial":
        return (
            f"{paid} rupees bhej diye aur baaki {approval} rupees ops team ko approval ke liye bhej diye{trip_text}."
            if decision.language == "hinglish"
            else f"{paid} rupees was paid and the remaining {approval} rupees was sent to ops for approval{trip_text}."
        )
    if decision.outcome == "nothing_owed":
        return (
            f"Record ke hisab se {expected} rupees ke hisab se koi payout nahi banta{trip_text}."
            if decision.language == "hinglish"
            else f"The records show {expected} rupees owed; no payout is due{trip_text}."
        )
    if decision.outcome == "already_paid":
        return (
            f"{expected} rupees ka payout already paid hai{trip_text}."
            if decision.language == "hinglish"
            else f"The {expected} rupees payout has already been paid{trip_text}."
        )
    if decision.outcome == "need_info":
        return (
            "Kaunse din ya kaunse order ka payout galat laga? Date ya order ID bata dijiye."
            if decision.language == "hinglish"
            else "Which date or order ID had the incorrect payout?"
        )
    if decision.outcome == "escalated":
        return (
            f"{approval} rupees ki request ops team ko escalate kar di hai{trip_text}."
            if decision.language == "hinglish"
            else f"The {approval} rupees request has been escalated to ops{trip_text}."
        )
    return (
        "Main sirf is account se jude payouts ki madad kar sakta hoon."
        if decision.language == "hinglish"
        else "I can only help with payouts linked to your account."
    )


def format_amount(value: object) -> str:
    from decimal import Decimal

    amount = Decimal(str(value))
    return str(int(amount)) if amount == amount.to_integral_value() else str(amount.normalize())


def reply_is_supported(reply: str, decision: ReplyDecision) -> bool:
    allowed_amounts = {format_amount(value) for value in decision.amounts.values()}
    rupee_mentions = re.findall(
        r"(?<![A-Za-z])(?:₹\s*|Rs\.?\s*|rupees?\s+)?"
        r"(\d+(?:\.\d{1,2})?)\s*(?:₹|rupees?)",
        reply,
        flags=re.IGNORECASE,
    )
    rupees_before_number = re.findall(
        r"(?:₹\s*|Rs\.?\s*)(\d+(?:\.\d{1,2})?)",
        reply,
        flags=re.IGNORECASE,
    )
    mentions = set(rupee_mentions + rupees_before_number)
    if not mentions <= allowed_amounts:
        return False

    reply_trip_ids = set(re.findall(r"\bT\d+\b", reply, flags=re.IGNORECASE))
    allowed_trip_ids = {trip_id.upper() for trip_id in decision.trip_ids}
    return {trip_id.upper() for trip_id in reply_trip_ids} <= allowed_trip_ids


async def write_reply(provider: LLMProvider, decision: ReplyDecision) -> str:
    prompt = (
        f"language: {decision.language}\n"
        f"structured decision: {decision.model_dump_json()}"
    )
    try:
        data = await provider.complete_json(prompt, system_prompt=REPLY_WRITER_SYSTEM)
        reply = str(data.get("reply", "")).strip()
    except Exception:
        return template_reply(decision)
    if not reply or not reply_is_supported(reply, decision):
        return template_reply(decision)
    return reply
