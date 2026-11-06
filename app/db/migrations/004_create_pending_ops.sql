CREATE TABLE IF NOT EXISTS pending_ops (
    id TEXT PRIMARY KEY,
    rider_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('approval', 'escalation')),
    amount INTEGER,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS pending_ops_status_idx
    ON pending_ops (status);
