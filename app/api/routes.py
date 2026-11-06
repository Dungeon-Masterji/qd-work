import os
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.models import Finding
from app.services.agent import handle_message
from app.services.payswift import PaySwiftClient
from app.services.trace import log_trace, rider_trace


router = APIRouter()


class MessageRequest(BaseModel):
    message_id: str = Field(min_length=1)
    rider_id: str = Field(min_length=1, pattern=r"^R\d+$")
    text: str = Field(min_length=1)
    received_at: datetime


class RejectRequest(BaseModel):
    note: str | None = None


def connection(request: Request) -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"])


def iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


@router.post("/messages")
async def messages(payload: MessageRequest, request: Request) -> dict[str, str]:
    db = connection(request)
    try:
        log_trace(
            db,
            payload.rider_id,
            "message_in",
            "incoming_message",
            payload.model_dump(mode="json"),
        )
        db.commit()
        try:
            reply = await handle_message(
                payload.message_id,
                payload.rider_id,
                payload.text,
                payload.received_at,
                connection=db,
            )
        except Exception as error:
            log_trace(
                db,
                payload.rider_id,
                "error",
                "agent_error",
                {"message_id": payload.message_id},
                {"error": str(error)},
            )
            db.commit()
            reply = "Abhi kuch technical dikkat aa rahi hai. Ops team ko dekhne ke liye bhej diya hai."
        log_trace(db, payload.rider_id, "reply", "agent_reply", None, reply)
        db.commit()
        return {"reply": reply}
    finally:
        db.close()


@router.get("/trace/{rider_id}")
async def trace(rider_id: str, request: Request) -> list[dict[str, Any]]:
    db = connection(request)
    try:
        return rider_trace(db, rider_id)
    finally:
        db.close()


@router.get("/ops/pending")
async def pending(request: Request) -> list[dict[str, Any]]:
    db = connection(request)
    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, rider_id, type, amount, reason, created_at
                FROM pending_ops
                WHERE status = 'pending'
                ORDER BY created_at, id
                """
            )
            rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "rider_id": row[1],
                "type": row[2],
                "amount": row[3],
                "reason": row[4],
                "created_at": iso(row[5]),
            }
            for row in rows
        ]
    finally:
        db.close()


def pay_ops_item(db: psycopg.Connection, item_id: str, payswift: PaySwiftClient) -> dict[str, Any]:
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT id, rider_id, type, amount, status FROM pending_ops WHERE id = %s FOR UPDATE",
            (item_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Ops item not found")
        if row[4] != "pending":
            raise HTTPException(status_code=409, detail=f"Ops item already {row[4]}")
        if row[2] != "approval":
            raise HTTPException(status_code=409, detail="Only approvals can be paid")
        amount = int(row[3])

    return {
        "rider_id": row[1],
        "amount": amount,
    }


async def add_follow_up(db: psycopg.Connection, rider_id: str, text: str) -> None:
    message_id = f"ops-{uuid4()}"
    with db.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO messages (message_id, rider_id, text, received_at, reply)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP, %s)
            """,
            (message_id, rider_id, text, text),
        )
        log_trace(db, rider_id, "reply", "ops_follow_up", None, text)


@router.post("/ops/{item_id}/approve")
async def approve(item_id: str, request: Request) -> dict[str, Any]:
    db = connection(request)
    try:
        with db.transaction():
            details = pay_ops_item(db, item_id, None)
            payswift = PaySwiftClient(
                os.environ.get("PAYSWIFT_BASE_URL", "http://localhost:8081")
            )
            payout = await payswift.payout(
                details["rider_id"],
                datetime.now().date(),
                [],
                Decimal(details["amount"]),
                f"ops:{item_id}",
            )
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE pending_ops
                    SET status = 'approved', resolved_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (item_id,),
                )
            await add_follow_up(
                db,
                details["rider_id"],
                f"{details['amount']} rupees ka approval payout process ho gaya hai.",
            )
        return {"id": item_id, "status": "approved", "payout": payout}
    finally:
        db.close()


@router.post("/ops/{item_id}/reject")
async def reject(item_id: str, payload: RejectRequest, request: Request) -> dict[str, Any]:
    db = connection(request)
    try:
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT rider_id, status, type FROM pending_ops WHERE id = %s FOR UPDATE",
                (item_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Ops item not found")
            if row[1] != "pending":
                raise HTTPException(status_code=409, detail=f"Ops item already {row[1]}")
            cursor.execute(
                """
                UPDATE pending_ops
                SET status = 'rejected', note = %s, resolved_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (payload.note, item_id),
            )
        await add_follow_up(
            db,
            row[0],
            "Ops team ne aapki request reject kar di hai"
            + (f": {payload.note}" if payload.note else "."),
        )
        db.commit()
        return {"id": item_id, "status": "rejected"}
    finally:
        db.close()


@router.get("/ops/riders")
async def ops_riders(request: Request) -> list[str]:
    db = connection(request)
    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT rider_id FROM messages
                UNION
                SELECT DISTINCT rider_id FROM pending_ops
                UNION
                SELECT DISTINCT rider_id FROM riders
                ORDER BY rider_id
                """
            )
            return [row[0] for row in cursor.fetchall()]
    finally:
        db.close()


@router.get("/ops/conversations/{rider_id}")
async def ops_conversations(rider_id: str, request: Request) -> list[dict[str, Any]]:
    db = connection(request)
    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT message_id, text, received_at, reply
                FROM messages WHERE rider_id = %s
                ORDER BY received_at, message_id
                """,
                (rider_id,),
            )
            return [
                {
                    "message_id": row[0],
                    "text": row[1],
                    "received_at": iso(row[2]),
                    "reply": row[3],
                }
                for row in cursor.fetchall()
            ]
    finally:
        db.close()
