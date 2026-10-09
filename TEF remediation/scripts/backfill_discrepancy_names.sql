-- Backfill: rename abbreviated discrepancy names to full branch names
-- in devops_reports.branch_drift_evidence.
--
-- Root cause: DISCREPANCY_DEFS in report_branch_discrepancies_by_content.py
-- used "prod" / "prod" abbreviations (e.g. "prod_not_in_test") while the
-- file_drift_report SQL view constructs its JOIN key from full branch names
-- (e.g. "production_not_in_test").  This caused a silent LEFT JOIN miss for
-- all four production-related directions, making files_added/modified/deleted
-- appear null even though evidence rows were present.
--
-- Fix applied in commit 309493f; this script patches historical rows so that
-- evidence collected before the fix also joins correctly.
--
-- Run once in BigQuery console or via bq query:
--   bq query --use_legacy_sql=false < backfill_discrepancy_names.sql
--
-- Safe to re-run: WHERE clause only matches the old names; rows already
-- renamed (or newly written after the fix) are untouched.

UPDATE `tefde-gcp-fastoss-dev.devops_reports.branch_drift_evidence`
SET discrepancy = CASE discrepancy
  WHEN 'prod_not_in_test'   THEN 'production_not_in_test'
  WHEN 'test_not_in_prod'   THEN 'test_not_in_production'
  WHEN 'prod_not_in_master' THEN 'production_not_in_master'
  WHEN 'master_not_in_prod' THEN 'master_not_in_production'
END
WHERE discrepancy IN (
  'prod_not_in_test',
  'test_not_in_prod',
  'prod_not_in_master',
  'master_not_in_prod'
);
