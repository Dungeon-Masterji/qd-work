CREATE TABLE IF NOT EXISTS trace_steps (
    id BIGSERIAL PRIMARY KEY,
    rider_id TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    type TEXT NOT NULL CHECK (type IN ('message_in', 'tool_call', 'decision', 'reply', 'error')),
    name TEXT NOT NULL,
    input JSONB,
    output JSONB
);

CREATE INDEX IF NOT EXISTS trace_steps_rider_id_at_idx
    ON trace_steps (rider_id, at);
