CREATE TABLE IF NOT EXISTS payouts_made (
    id BIGSERIAL PRIMARY KEY,
    rider_id TEXT NOT NULL,
    amount INTEGER NOT NULL,
    reference TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payswift_payout_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS payouts_made_rider_created_idx
    ON payouts_made (rider_id, created_at);
