ALTER TABLE pending_ops
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS note TEXT;

ALTER TABLE pending_ops
    DROP CONSTRAINT IF EXISTS pending_ops_type_check,
    DROP CONSTRAINT IF EXISTS pending_ops_status_check;

ALTER TABLE pending_ops
    ADD CONSTRAINT pending_ops_type_check
        CHECK (type IN ('approval', 'escalation')),
    ADD CONSTRAINT pending_ops_status_check
        CHECK (status IN ('pending', 'approved', 'rejected'));

ALTER TABLE trace_steps
    DROP CONSTRAINT IF EXISTS trace_steps_type_check;

ALTER TABLE trace_steps
    ADD CONSTRAINT trace_steps_type_check
        CHECK (type IN ('message_in', 'tool_call', 'decision', 'reply', 'error'));

CREATE INDEX IF NOT EXISTS trace_steps_rider_id_at_idx
    ON trace_steps (rider_id, at);

CREATE INDEX IF NOT EXISTS pending_ops_status_idx
    ON pending_ops (status);
