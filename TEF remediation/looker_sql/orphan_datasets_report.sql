/*
 * Orphan BigQuery Datasets Report
 *
 * Purpose : Surface BigQuery datasets that have no corresponding source-code
 *           definition, indicating unmanaged, stale, or shadow datasets.
 *           Includes storage and row-count metrics for each dataset's objects.
 * Tables  : devops_reports.executions
 *           devops_reports.orphan_datasets
 *           devops_reports.orphan_dataset_objects
 * Usage   : Replace <GCP_PROJECT> with your GCP project ID.
 *           In Looker, register as a native derived table or run via SQL Runner.
 *           In Looker Studio, use as a Custom Query data source.
 *
 * Suggested dashboard tiles:
 *   - Orphan dataset count by status : bar / pie — orphan_status breakdown
 *   - Storage at risk                : SUM(total_storage_mb) for confirmed orphans
 *   - Top owners with orphan datasets: table — owner × dataset_count
 *   - Risk score distribution        : histogram of risk_score
 *   - Orphan timeline                : dataset count trended over execution_ts
 */

-- ──────────────────────────────────────────────────────────────────────────────
-- Summary — one row per orphan dataset, enriched with object-level aggregates
-- ──────────────────────────────────────────────────────────────────────────────
WITH latest_exec AS (
  SELECT
    execution_id,
    execution_ts,
    environment,
    status,
    triggered_by
  FROM `<GCP_PROJECT>.devops_reports.executions`
  WHERE report_type = 'orphan_datasets'
    AND status      = 'success'
  QUALIFY ROW_NUMBER() OVER (ORDER BY execution_ts DESC) = 1
),

datasets AS (
  SELECT
    d.execution_id,
    d.dataset_name,
    d.project_id,
    d.orphan_status,
    d.source_reference_found,
    d.last_modified,
    d.table_count,
    d.owner,
    d.risk_score,
    DATE_DIFF(CURRENT_DATE(), DATE(d.last_modified), DAY) AS days_since_modified
  FROM `<GCP_PROJECT>.devops_reports.orphan_datasets` d
  JOIN latest_exec USING (execution_id)
),

objects_agg AS (
  SELECT
    o.execution_id,
    o.dataset_name,
    COUNT(DISTINCT o.object_name)              AS object_count,
    SUM(o.row_count)                           AS total_row_count,
    ROUND(SUM(o.storage_mb), 2)                AS total_storage_mb,
    COUNTIF(UPPER(o.object_type) = 'TABLE')    AS table_objects,
    COUNTIF(UPPER(o.object_type) = 'VIEW')     AS view_objects,
    COUNTIF(
      UPPER(o.object_type) NOT IN ('TABLE','VIEW')
    )                                          AS other_objects,
    MAX(o.last_modified)                       AS most_recent_object_change
  FROM `<GCP_PROJECT>.devops_reports.orphan_dataset_objects` o
  JOIN latest_exec USING (execution_id)
  GROUP BY
    o.execution_id,
    o.dataset_name
)

SELECT
  e.execution_ts,
  e.environment,
  e.triggered_by,
  d.project_id,
  d.dataset_name,
  d.orphan_status,
  d.source_reference_found,
  d.owner,
  d.risk_score,
  d.last_modified          AS dataset_last_modified,
  d.days_since_modified,
  d.table_count            AS reported_table_count,
  COALESCE(oa.object_count,    0)  AS scanned_object_count,
  COALESCE(oa.table_objects,   0)  AS scanned_tables,
  COALESCE(oa.view_objects,    0)  AS scanned_views,
  COALESCE(oa.other_objects,   0)  AS scanned_other_objects,
  COALESCE(oa.total_row_count, 0)  AS total_row_count,
  COALESCE(oa.total_storage_mb,0)  AS total_storage_mb,
  oa.most_recent_object_change
FROM latest_exec e
JOIN datasets d USING (execution_id)
LEFT JOIN objects_agg oa
  ON  oa.execution_id = d.execution_id
  AND oa.dataset_name = d.dataset_name
ORDER BY
  d.risk_score DESC,
  d.total_storage_mb DESC,
  d.dataset_name;


-- ──────────────────────────────────────────────────────────────────────────────
-- Status Breakdown — aggregate counts for scorecard tiles
-- Run independently in SQL Runner or as a separate Looker tile.
-- ──────────────────────────────────────────────────────────────────────────────
/*
WITH latest_exec AS (
  SELECT execution_id, execution_ts, environment
  FROM `<GCP_PROJECT>.devops_reports.executions`
  WHERE report_type = 'orphan_datasets'
    AND status      = 'success'
  QUALIFY ROW_NUMBER() OVER (ORDER BY execution_ts DESC) = 1
)

SELECT
  e.execution_ts,
  e.environment,
  d.orphan_status,
  d.project_id,
  COUNT(*)                                AS dataset_count,
  COUNTIF(NOT d.source_reference_found)  AS no_code_reference,
  SUM(d.table_count)                     AS total_tables,
  ROUND(AVG(d.risk_score), 1)            AS avg_risk_score,
  MAX(d.risk_score)                      AS max_risk_score
FROM `<GCP_PROJECT>.devops_reports.orphan_datasets` d
JOIN latest_exec e USING (execution_id)
GROUP BY
  e.execution_ts, e.environment, d.orphan_status, d.project_id
ORDER BY
  d.orphan_status,
  dataset_count DESC;
*/


-- ──────────────────────────────────────────────────────────────────────────────
-- Object Detail — one row per object within orphan datasets (for drill-through)
-- Run independently in SQL Runner or as a separate Looker tile.
-- ──────────────────────────────────────────────────────────────────────────────
/*
WITH latest_exec AS (
  SELECT execution_id, execution_ts, environment
  FROM `<GCP_PROJECT>.devops_reports.executions`
  WHERE report_type = 'orphan_datasets'
    AND status      = 'success'
  QUALIFY ROW_NUMBER() OVER (ORDER BY execution_ts DESC) = 1
),

orphan_ds AS (
  SELECT execution_id, dataset_name, project_id, orphan_status, risk_score, owner
  FROM `<GCP_PROJECT>.devops_reports.orphan_datasets`
  JOIN latest_exec USING (execution_id)
)

SELECT
  e.execution_ts,
  e.environment,
  ds.project_id,
  ds.dataset_name,
  ds.orphan_status,
  ds.risk_score,
  ds.owner,
  o.object_type,
  o.object_name,
  o.last_modified,
  o.row_count,
  ROUND(o.storage_mb, 4)       AS storage_mb
FROM `<GCP_PROJECT>.devops_reports.orphan_dataset_objects` o
JOIN latest_exec e USING (execution_id)
JOIN orphan_ds ds
  ON  ds.execution_id = o.execution_id
  AND ds.dataset_name = o.dataset_name
ORDER BY
  ds.risk_score DESC,
  ds.dataset_name,
  o.object_type,
  o.object_name;
*/
