-- Stop the metering version first. Removes only this feature's data.
BEGIN;
DROP TABLE IF EXISTS token_usage_confirmed_daily, token_usage_calls, token_usage_install;
COMMIT;
