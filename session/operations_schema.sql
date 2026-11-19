CREATE TABLE IF NOT EXISTS operations_coverage (
    metric text PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO operations_coverage(metric) VALUES ('live') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS operations_questions (
    id bigint PRIMARY KEY, occurred_at timestamptz NOT NULL,
    user_id text NOT NULL, role text NOT NULL, session_id text NOT NULL,
    topic text, keywords text[] NOT NULL DEFAULT '{}', repeated boolean
);
CREATE INDEX IF NOT EXISTS operations_questions_time ON operations_questions(occurred_at,role);
CREATE TABLE IF NOT EXISTS operations_active_days (
    day date NOT NULL, user_id text NOT NULL, role text NOT NULL,
    PRIMARY KEY(day,user_id,role)
);
CREATE TABLE IF NOT EXISTS operations_first_activity (
    user_id text PRIMARY KEY, occurred_at timestamptz NOT NULL, role text NOT NULL
);
CREATE INDEX IF NOT EXISTS operations_first_time ON operations_first_activity(occurred_at,role);

CREATE TABLE IF NOT EXISTS operations_answers (
    id text PRIMARY KEY, occurred_at timestamptz NOT NULL, role text NOT NULL,
    user_id text NOT NULL, message_id bigint, revision integer,
    route text NOT NULL, success boolean NOT NULL, error text,
    first_ms integer, elapsed_ms integer, searches integer NOT NULL,
    hits integer NOT NULL, empty_searches integer NOT NULL, cited boolean NOT NULL, used_web boolean NOT NULL,
    documents text[] NOT NULL
);
CREATE INDEX IF NOT EXISTS operations_answers_time ON operations_answers(occurred_at,role);
CREATE INDEX IF NOT EXISTS operations_answers_version ON operations_answers(user_id,message_id,revision)
    WHERE success;

CREATE TABLE IF NOT EXISTS operations_tools (
    id text PRIMARY KEY, occurred_at timestamptz NOT NULL, role text NOT NULL, user_id text NOT NULL,
    name text NOT NULL, error text, elapsed_ms integer NOT NULL,
    keyword text, results integer
);
CREATE INDEX IF NOT EXISTS operations_tools_time ON operations_tools(occurred_at,role);
CREATE TABLE IF NOT EXISTS operations_gap_marks (
    keyword text PRIMARY KEY, state text NOT NULL CHECK (state IN ('fixed','ignored')),
    marked_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS operations_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, occurred_at timestamptz NOT NULL DEFAULT now(),
    kind text NOT NULL, object_id text, actor_id text
);
CREATE INDEX IF NOT EXISTS operations_events_time ON operations_events(occurred_at,kind);
CREATE TABLE IF NOT EXISTS operations_alerts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, rule text NOT NULL,
    triggered_at timestamptz NOT NULL DEFAULT now(), recovered_at timestamptz, value double precision NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS operations_alert_active ON operations_alerts(rule) WHERE recovered_at IS NULL;

CREATE TABLE IF NOT EXISTS operations_daily (
    day date PRIMARY KEY, totals jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS operations_rollup_pending (
    day date PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS operations_daily_traffic (
    day date NOT NULL, scope text NOT NULL, active bigint NOT NULL, sessions bigint NOT NULL,
    PRIMARY KEY(day,scope)
);
