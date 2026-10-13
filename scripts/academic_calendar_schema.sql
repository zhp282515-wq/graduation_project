-- 校历结构化表：一个学期一行（academic_term）+ 学期内各类事件（academic_calendar）。
-- 网格（周次×日期）不落库，由 academic_term.term_start 派生：
--     第 n 周周一 = term_start + 7 * (n - 1)   （term_start = 第 1 周周一 = 正式上课日）

CREATE TABLE IF NOT EXISTS academic_term (
    id            BIGSERIAL PRIMARY KEY,
    academic_year TEXT     NOT NULL,                 -- '2026-2027'
    term          TEXT     NOT NULL CHECK (term IN ('spring', 'fall')),
    term_start    DATE     NOT NULL,                 -- 第 1 周周一 = 正式上课日
    term_end      DATE     NOT NULL,                 -- 学期最后一天（含）
    UNIQUE (academic_year, term),
    CHECK (term_end >= term_start)
);

CREATE TABLE IF NOT EXISTS academic_calendar (
    id              BIGSERIAL PRIMARY KEY,
    term_id         BIGINT   NOT NULL REFERENCES academic_term(id) ON DELETE CASCADE,
    event_type      TEXT     NOT NULL,
    name            TEXT     NOT NULL,
    start_date      DATE     NOT NULL,
    end_date        DATE     NOT NULL,
    affects_weekday SMALLINT CHECK (affects_weekday BETWEEN 1 AND 7),
    audience        TEXT     NOT NULL DEFAULT 'all'
                    CHECK (audience IN ('all', 'undergrad', 'graduate', 'staff')),
    is_tentative    BOOLEAN  NOT NULL DEFAULT FALSE,
    note            TEXT,
    source_file     TEXT,                                    -- 来源 YAML，便于溯源
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_academic_calendar_range
    ON academic_calendar (start_date, end_date);