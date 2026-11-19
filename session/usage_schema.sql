CREATE TABLE IF NOT EXISTS token_usage_install (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    started_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO token_usage_install(singleton) VALUES (true) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS token_usage_calls (
    event_id text PRIMARY KEY,
    user_id text NOT NULL,
    role text NOT NULL CHECK (role IN ('user','admin')),
    session_id text,
    model text NOT NULL,
    input_tokens bigint CHECK (input_tokens >= 0),
    output_tokens bigint CHECK (output_tokens >= 0),
    total_tokens bigint NOT NULL CHECK (total_tokens > 0 AND total_tokens >= coalesce(input_tokens,0) + coalesce(output_tokens,0)),
    source text NOT NULL CHECK (source IN ('chat','tool_loop','other')),
    estimated boolean NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS token_usage_calls_time ON token_usage_calls(created_at,role);

CREATE TABLE IF NOT EXISTS token_usage_confirmed_daily (
    day date NOT NULL,
    user_id text NOT NULL,
    role text NOT NULL,
    input_tokens bigint NOT NULL,
    output_tokens bigint NOT NULL,
    total_tokens bigint NOT NULL,
    calls bigint NOT NULL,
    PRIMARY KEY (day,user_id,role)
);
