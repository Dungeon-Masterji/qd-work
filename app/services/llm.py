import json
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from app.models import IntentIssue, IntentIssueType, IntentOutput


LLM_TIMEOUT_SECONDS = 4.0
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)


class LLMProvider(ABC):
    @abstractmethod
    async def complete_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        ...


class GroqProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport

    async def complete_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        async with httpx.AsyncClient(
            timeout=LLM_TIMEOUT_SECONDS,
            transport=self.transport,
        ) as client:
            response = await client.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return parse_json_response(content)


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport

    async def complete_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"responseMimeType": "application/json"},
        }
        if system_prompt:
            body["systemInstruction"] = {
                "parts": [{"text": system_prompt}],
            }
        url = GEMINI_URL.format(model=self.model)
        async with httpx.AsyncClient(
            timeout=LLM_TIMEOUT_SECONDS,
            transport=self.transport,
        ) as client:
            response = await client.post(
                url,
                params={"key": self.api_key},
                json=body,
            )
            response.raise_for_status()
        content = (
            response.json()["candidates"][0]["content"]["parts"][0]["text"]
        )
        return parse_json_response(content)


def parse_json_response(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content, parse_float=Decimal)
    except json.JSONDecodeError as error:
        raise ValueError("LLM response was not valid JSON") from error
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


def regex_parse_intent(message: str, received_at: datetime) -> IntentOutput:
    lowered = message.lower()
    trip_ids = [
        trip.upper() for trip in re.findall(r"\bT\d+\b", message, re.IGNORECASE)
    ]
    trip_id = trip_ids[0] if trip_ids else None

    issue_type = IntentIssueType.PAYOUT_WRONG_VAGUE
    if "surge" in lowered:
        issue_type = IntentIssueType.MISSING_SURGE
    elif "distance" in lowered:
        issue_type = IntentIssueType.WRONG_DISTANCE_PAY
    elif "incentive" in lowered:
        issue_type = IntentIssueType.MISSING_INCENTIVE
    elif "penalty" in lowered or "cancel" in lowered:
        issue_type = IntentIssueType.CANCEL_PENALTY

    issue_date = None
    if "kal" in lowered:
        issue_date = received_at.date() - timedelta(days=1)
    elif "parso" in lowered:
        issue_date = received_at.date() - timedelta(days=2)
    else:
        day_match = re.search(
            r"\b(?:sep(?:tember)?|sept)\s+(\d{1,2})(?:st|nd|rd|th)?\b"
            r"|\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:sep(?:tember)?|sept)\b"
            r"|\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+(?:wala|tarikh))?\b",
            lowered,
        )
        if day_match:
            day = next(int(value) for value in day_match.groups() if value)
            issue_date = received_at.date().replace(day=day)

    claimed_amount = None
    amount_match = re.search(
        r"\b(?:rs\.?|rupay|rupees?)\s*(\d+(?:\.\d+)?)\b|\b(\d+(?:\.\d+)?)\s*(?:rs\.?|rupay|rupees?)\b",
        lowered,
    )
    if amount_match:
        claimed_amount = Decimal(amount_match.group(1) or amount_match.group(2))
    else:
        claimed_number_match = re.search(
            r"\b(\d+(?:\.\d+)?)\s+(?:kam|less)\b",
            lowered,
        )
        if claimed_number_match:
            claimed_amount = Decimal(claimed_number_match.group(1))

    claimed_count = None
    count_match = re.search(
        r"\b(\d+)\s*(?:orders?|trips?|ride(?:s)?|complete(?:d)?(?: orders?)?)\b",
        lowered,
    )
    if count_match and "incentive" in lowered:
        claimed_count = int(count_match.group(1))

    issue = IntentIssue(
        type=issue_type,
        trip_id=trip_id,
        date=issue_date,
        claimed_amount=claimed_amount,
        claimed_trip_count=claimed_count,
    )
    suspicious = bool(
        re.search(r"\bsystem\b|ignore (?:all )?previous|approve everything", lowered)
        or re.search(r"\bthis is r\d+", lowered)
    )
    wants_human = bool(
        re.search(r"\baccident\b|emergency|manager|person|legal", lowered)
    )
    unclear = issue_type == IntentIssueType.PAYOUT_WRONG_VAGUE and not issue_date and not trip_id
    language = "english" if re.fullmatch(r"[\x00-\x7f\s]*", message) and not re.search(r"[a-z]*(?:nahi|kyun|wala|mila|kaata|hu[a-z]*)", lowered) else "hinglish"
    return IntentOutput(
        issues=[issue],
        needs_clarification=unclear,
        clarification_question=(
            "Kaunse din ya kaunse order ka payout galat laga? Date ya order ID bata dijiye."
            if unclear else None
        ),
        language=language,
        suspicious=suspicious,
        wants_human=wants_human,
    )


async def complete_intent(
    provider: LLMProvider,
    message: str,
    received_at: datetime,
    *,
    history: str = "",
) -> IntentOutput:
    from app.services.prompts import INTENT_SYSTEM, INTENT_USER_TEMPLATE

    prompt = INTENT_USER_TEMPLATE.format(
        received_at=received_at.isoformat(),
        history=history,
        message=message,
    )
    try:
        data = await provider.complete_json(prompt, system_prompt=INTENT_SYSTEM)
        return IntentOutput.model_validate(data)
    except Exception:
        return regex_parse_intent(message, received_at)


def get_llm_provider(
    provider_name: str | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LLMProvider:
    provider_name = (
        provider_name or os.environ.get("LLM_PROVIDER", "groq")
    ).lower()
    if provider_name == "groq":
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        return GroqProvider(api_key, transport=transport)
    if provider_name == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is required when LLM_PROVIDER=gemini"
            )
        return GeminiProvider(api_key, transport=transport)
    raise ValueError(
        f"Unsupported LLM_PROVIDER '{provider_name}'. Use 'groq' or 'gemini'."
    )
