BEGIN;
DROP TABLE IF EXISTS operations_daily_traffic, operations_rollup_pending, operations_daily,
  operations_alerts, operations_events, operations_gap_marks,
  operations_tools, operations_answers, operations_first_activity, operations_active_days,
  operations_questions, operations_coverage;
COMMIT;
