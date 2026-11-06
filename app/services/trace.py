import json
from datetime import datetime, timezone
from typing import Any

import psycopg


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def log_trace(
    connection: psycopg.Connection,
    rider_id: str,
    step_type: str,
    name: str,
    input_value: Any = None,
    output_value: Any = None,
    at: datetime | None = None,
) -> None:
    if step_type not in {"message_in", "tool_call", "decision", "reply", "error"}:
        raise ValueError(f"Invalid trace step type: {step_type}")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO trace_steps (rider_id, at, type, name, input, output)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
            """,
            (
                rider_id,
                at or datetime.now(timezone.utc),
                step_type,
                name,
                _json(input_value),
                _json(output_value),
            ),
        )


def rider_trace(
    connection: psycopg.Connection,
    rider_id: str,
) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT at, type, name, input, output
            FROM trace_steps
            WHERE rider_id = %s
            ORDER BY at, id
            """,
            (rider_id,),
        )
        rows = cursor.fetchall()
    return [
        {
            "at": at.isoformat(),
            "type": step_type,
            "name": name,
            "input": input_value,
            "output": output_value,
        }
        for at, step_type, name, input_value, output_value in rows
    ]
