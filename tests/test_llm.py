from datetime import datetime

import pytest

from app.services.llm import LLMProvider, complete_intent


class StaticProvider(LLMProvider):
    def __init__(self, data: object | Exception) -> None:
        self.data = data

    async def complete_json(self, prompt, *, system_prompt=None):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


@pytest.mark.asyncio
async def test_invalid_llm_output_falls_back_to_regex():
    result = await complete_intent(
        StaticProvider({"issues": [{"type": "not_a_real_issue"}]}),
        "21 ko 300 rupay kam aaye, order T980582 ka surge nahi mila",
        datetime(2026, 9, 23, 11, 45),
    )

    assert result.issues[0].type.value == "missing_surge"
    assert result.issues[0].trip_id == "T980582"
    assert str(result.issues[0].claimed_amount) == "300"


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_regex():
    result = await complete_intent(
        StaticProvider(RuntimeError("provider unavailable")),
        "order T252921 pe surge kam aaya",
        datetime(2026, 9, 23, 11, 45),
    )

    assert result.issues[0].type.value == "missing_surge"
    assert result.issues[0].trip_id == "T252921"
