CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    rider_id TEXT NOT NULL,
    text TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    reply TEXT
);
