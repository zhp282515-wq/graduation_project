CREATE TABLE IF NOT EXISTS feedback_started (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    started_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO feedback_started DEFAULT VALUES ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS answer_revisions (
    message_id bigint PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    revision integer NOT NULL CHECK (revision > 0)
);

CREATE TABLE IF NOT EXISTS answer_ratings (
    user_id text NOT NULL,
    message_id bigint NOT NULL,
    revision integer NOT NULL,
    role text NOT NULL CHECK (role IN ('user', 'admin')),
    vote text NOT NULL CHECK (vote IN ('like', 'dislike')),
    reason text,
    voted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, message_id, revision)
);
CREATE INDEX IF NOT EXISTS answer_ratings_time ON answer_ratings(voted_at, role);

CREATE TABLE IF NOT EXISTS feedback_entries (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id text NOT NULL,
    submission_id uuid NOT NULL,
    category text NOT NULL,
    description text NOT NULL,
    message_id bigint,
    revision integer,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, submission_id)
);
CREATE INDEX IF NOT EXISTS feedback_user_time ON feedback_entries(user_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS feedback_time ON feedback_entries(created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS feedback_processing (
    entry_id bigint PRIMARY KEY REFERENCES feedback_entries(id) ON DELETE CASCADE,
    processed boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_attachments (
    entry_id bigint NOT NULL REFERENCES feedback_entries(id) ON DELETE CASCADE,
    position smallint NOT NULL CHECK (position BETWEEN 1 AND 3),
    media_type text NOT NULL,
    data bytea NOT NULL CHECK (octet_length(data) <= 10485760),
    PRIMARY KEY (entry_id, position)
);
