CREATE TABLE IF NOT EXISTS riders (
    rider_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    joined_on DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS trips (
    trip_id TEXT PRIMARY KEY,
    rider_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    distance_km NUMERIC NOT NULL,
    surge_multiplier NUMERIC NOT NULL
);

CREATE INDEX IF NOT EXISTS trips_rider_started_at_idx
    ON trips (rider_id, started_at);

CREATE TABLE IF NOT EXISTS payout_lines (
    line_id TEXT PRIMARY KEY,
    payout_date DATE NOT NULL,
    rider_id TEXT NOT NULL,
    line_type TEXT NOT NULL,
    trip_id TEXT,
    amount NUMERIC NOT NULL
);
