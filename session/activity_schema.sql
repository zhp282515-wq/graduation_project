CREATE TABLE IF NOT EXISTS usage_activity_install (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    started_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO usage_activity_install DEFAULT VALUES ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS usage_activity_events (
    event_id text PRIMARY KEY,
    occurred_at timestamptz NOT NULL,
    role text NOT NULL CHECK (role IN ('user', 'admin')),
    tool_name text
);
CREATE INDEX IF NOT EXISTS usage_activity_time ON usage_activity_events(occurred_at,role);
