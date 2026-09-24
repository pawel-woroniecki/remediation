-- BQ Structure Drift report view
-- Reference SQL for Looker Studio custom queries.
-- The primary data source is the `bq_structure_drift_report` view in BigQuery.
--
-- Filter on run_number = 1 to see only the most recent run.
-- Filter on run_date to browse historical snapshots.

SELECT
  run_id,
  checked_at,
  DATE(checked_at)  AS run_date,
  dataset_id,
  table_id,
  table_type,
  discrepancy,
  attribute,
  prod_value,
  test_value,
  dev_gke_value,
  ROW_NUMBER() OVER (
    PARTITION BY dataset_id, table_id, attribute
    ORDER BY checked_at DESC
  ) AS run_number
FROM `tefde-gcp-fastoss-dev.devops_reports.bq_structure_drift`
