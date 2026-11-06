import json
import os
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

from app.models import IntentOutput, ReplyDecision
from app.services.guardrails import decide
from app.services.ledger import reconcile_ledger
from app.services.llm import complete_intent, get_llm_provider
from app.services.payswift import PaySwiftClient
from app.services.replies import template_reply, write_reply


DEFAULT_RIDER_STATE = {
    "open_issue": None,
    "discussed_dates": [],
    "discussed_trips": [],
    "settled_findings": [],
    "history": [],
}


def finding_identity(finding: Any) -> str:
    return finding.trip_id or (
        finding.date.isoformat() if finding.date else finding.type.value
    )


class Agent:
    def __init__(
        self,
        connection: psycopg.Connection | None = None,
        *,
        llm=None,
        payswift: PaySwiftClient | None = None,
    ) -> None:
        self.connection = connection
        self.llm = llm
        self.payswift = payswift

    def _connection(self) -> psycopg.Connection:
        if self.connection is not None:
            return self.connection
        return psycopg.connect(os.environ["DATABASE_URL"])

    def _state(self, rider_id: str, connection: psycopg.Connection) -> dict[str, Any]:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT state FROM rider_state WHERE rider_id = %s",
                (rider_id,),
            )
            row = cursor.fetchone()
        state = json.loads(row[0]) if row and isinstance(row[0], str) else (row[0] if row else {})
        return {**DEFAULT_RIDER_STATE, **state}

    def _save(
        self,
        rider_id: str,
        state: dict[str, Any],
        connection: psycopg.Connection,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO rider_state (rider_id, state, updated_at)
                VALUES (%s, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (rider_id) DO UPDATE
                SET state = EXCLUDED.state, updated_at = CURRENT_TIMESTAMP
                """,
                (rider_id, json.dumps(state, default=str)),
            )

    async def handle_message(
        self,
        message_id: str,
        rider_id: str,
        text: str,
        received_at: datetime,
    ) -> str:
        connection = self._connection()
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT reply FROM messages WHERE message_id = %s AND rider_id = %s",
                    (message_id, rider_id),
                )
                existing = cursor.fetchone()
                if existing:
                    return existing[0] or ""
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"rider:{rider_id}",),
                )
                cursor.execute(
                    """
                    INSERT INTO messages (message_id, rider_id, text, received_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (message_id) DO NOTHING
                    """,
                    (message_id, rider_id, text, received_at),
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        "SELECT reply FROM messages WHERE message_id = %s",
                        (message_id,),
                    )
                    stored = cursor.fetchone()
                    if stored:
                        return stored[0] or ""

            state = self._state(rider_id, connection)
            history = state["history"][-6:]
            llm = self.llm or get_llm_provider()
            intent = await complete_intent(
                llm,
                text,
                received_at,
                history="\n".join(str(turn) for turn in history),
            )

            reply, state = await self._process(
                connection,
                rider_id,
                text,
                received_at,
                intent,
                state,
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE messages SET reply = %s
                    WHERE message_id = %s AND rider_id = %s
                    """,
                    (reply, message_id, rider_id),
                )
            state["history"] = (history + [
                {"role": "rider", "text": text},
                {"role": "agent", "text": reply},
            ])[-6:]
            self._save(rider_id, state, connection)
            return reply

    async def _process(
        self,
        connection: psycopg.Connection,
        rider_id: str,
        text: str,
        received_at: datetime,
        intent: IntentOutput,
        state: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        if intent.message_kind.value == "thanks_or_ack":
            return "Thik hai. Koi aur payout issue ho to bata dijiye.", state

        suspicious = intent.suspicious or bool(
            re.search(r"\bsystem\s*:?\s*ignore all rules", text, re.IGNORECASE)
            or re.search(r"\bthis is\s+r\d+", text, re.IGNORECASE)
        )
        if suspicious:
            decision = ReplyDecision(
                outcome="escalated",
                language=intent.language.value,
                amounts={},
                facts=[intent.suspicious_reason or "Suspicious rider message"],
            )
            self._queue(connection, rider_id, Decimal("0"), "escalation", intent.suspicious_reason or "suspicious message")
            return await write_reply(self.llm or get_llm_provider(), decision) if self.llm else template_reply(decision), state

        issue = intent.issues[0] if intent.issues else None
        if intent.needs_clarification and issue:
            state["open_issue"] = issue.model_dump(mode="json", default=str)
            return intent.clarification_question or template_reply(
                ReplyDecision(outcome="need_info", language=intent.language.value)
            ), state

        if intent.message_kind.value == "followup_answer" and state.get("open_issue"):
            issue_data = state["open_issue"]
            if issue and issue.date:
                issue_data["date"] = issue.date.isoformat()
            if issue and issue.trip_id:
                issue_data["trip_id"] = issue.trip_id
            issue = IntentOutput.model_validate({
                "issues": [issue_data],
                "message_kind": "new_dispute",
                "language": intent.language.value,
            }).issues[0]

        if intent.needs_clarification or issue is None:
            return template_reply(ReplyDecision(outcome="need_info", language=intent.language.value)), state

        trip_id = issue.trip_id
        payout_date = issue.date
        if trip_id:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT started_at FROM trips WHERE rider_id = %s AND trip_id = %s",
                    (rider_id, trip_id),
                )
                trip_row = cursor.fetchone()
                if trip_row and not self._in_received_window(trip_row[0], received_at):
                    decision = ReplyDecision(
                        outcome="escalated",
                        language=intent.language.value,
                        amounts={},
                        trip_ids=[trip_id],
                        facts=["Trip is outside the last 7 days"],
                    )
                    self._queue(connection, rider_id, Decimal("0"), "escalation", "Trip outside 7-day window")
                    return template_reply(decision), state
            if not trip_row:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM trips WHERE trip_id = %s",
                        (trip_id,),
                    )
                    known_elsewhere = cursor.fetchone()
                reason = "Trip belongs to another rider" if known_elsewhere else "Unknown trip"
                decision = ReplyDecision(
                    outcome="not_your_account" if known_elsewhere else "escalated",
                    language=intent.language.value,
                    amounts={},
                    trip_ids=[trip_id],
                    facts=[reason],
                )
                self._queue(connection, rider_id, Decimal("0"), "escalation", reason)
                return template_reply(decision), state
        ledger = reconcile_ledger(
            connection,
            rider_id,
            trip_id=trip_id,
            payout_date=payout_date,
        )

        if ledger.difference <= 0 and ledger.findings:
            already = [finding for finding in ledger.findings if finding.trip_id in state.get("settled_findings", [])]
            if already:
                decision = ReplyDecision(
                    outcome="already_paid",
                    language=intent.language.value,
                    amounts={"owed": Decimal("0")},
                )
                return template_reply(decision), state

        active_findings = [
            finding
            for finding in ledger.findings
            if finding_identity(finding) not in {
                item["finding_id"] for item in state.get("settled_findings", [])
            }
        ]
        if not active_findings:
            if state.get("settled_findings"):
                return template_reply(ReplyDecision(
                    outcome="already_paid",
                    language=intent.language.value,
                    amounts={"owed": ledger.actual_total},
                )), state
            return template_reply(ReplyDecision(
                outcome="nothing_owed",
                language=intent.language.value,
                amounts={"owed": Decimal("0")},
                trip_ids=[trip_id] if trip_id else [],
            )), state

        payswift = self.payswift or PaySwiftClient(
            os.environ.get("PAYSWIFT_BASE_URL", "http://localhost:8081")
        )
        auto_pay, approval = await decide(
            rider_id,
            active_findings,
            received_at,
            payswift=payswift,
            ledger=ledger,
        )
        paid_findings = active_findings[:1]
        if auto_pay > 0:
            result = await payswift.payout(
                rider_id,
                received_at.date(),
                paid_findings,
                auto_pay,
                f"{rider_id}:{finding_identity(paid_findings[0])}",
            )
            payout_id = str(result.get("payout_id") or result.get("id") or result.get("reference"))
            settled = state.setdefault("settled_findings", [])
            for finding in paid_findings:
                settled.append({"finding_id": finding_identity(finding), "payout_id": payout_id})

        if approval > 0:
            self._queue(connection, rider_id, Decimal(approval), "approval", "Ledger amount requires approval")

        if auto_pay > 0 and approval > 0:
            decision = ReplyDecision(
                outcome="partial",
                language=intent.language.value,
                amounts={"paid": Decimal(auto_pay), "approval": Decimal(approval)},
                trip_ids=[finding.trip_id for finding in active_findings if finding.trip_id],
            )
        elif auto_pay > 0:
            decision = ReplyDecision(
                outcome="paid",
                language=intent.language.value,
                amounts={"paid": Decimal(auto_pay)},
                trip_ids=[finding.trip_id for finding in paid_findings if finding.trip_id],
            )
        else:
            decision = ReplyDecision(
                outcome="escalated",
                language=intent.language.value,
                amounts={"approval": Decimal(approval)},
                trip_ids=[finding.trip_id for finding in active_findings if finding.trip_id],
            )
        state["open_issue"] = None
        return (await write_reply(self.llm or get_llm_provider(), decision) if self.llm else template_reply(decision)), state

    def _queue(
        self,
        connection: psycopg.Connection,
        rider_id: str,
        amount: Decimal,
        operation_type: str,
        reason: str,
    ) -> None:
        operation_id = f"{rider_id}:{operation_type}:{reason[:32]}"
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO pending_ops (id, rider_id, type, amount, reason, status)
                VALUES (%s, %s, %s, %s, %s, 'pending')
                ON CONFLICT (id) DO NOTHING
                """,
                (operation_id, rider_id, operation_type, int(amount) if amount else None, reason),
            )

    @staticmethod
    def _in_received_window(trip_started_at: datetime, received_at: datetime) -> bool:
        from app.services.policy import in_window

        return in_window(trip_started_at.date(), received_at)


async def handle_message(
    message_id: str,
    rider_id: str,
    text: str,
    received_at: datetime,
    *,
    connection: psycopg.Connection | None = None,
    llm=None,
    payswift: PaySwiftClient | None = None,
) -> str:
    return await Agent(
        connection,
        llm=llm,
        payswift=payswift,
    ).handle_message(message_id, rider_id, text, received_at)
