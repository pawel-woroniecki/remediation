/*
 * Environment vs. Code Drift Report
 *
 * Purpose : Show discrepancies between what is defined in source code (git)
 *           and what is actually deployed in GCP environments.  Surfaces
 *           objects that exist in an environment but have no code definition
 *           (shadow resources) and code objects not yet deployed.
 * Tables  : devops_reports.executions
 *           devops_reports.env_drift_findings
 * Usage   : Replace <GCP_PROJECT> with your GCP project ID.
 *           In Looker, register as a native derived table or run via SQL Runner.
 *           In Looker Studio, use as a Custom Query data source.
 *
 * Suggested dashboard tiles:
 *   - Drift by product / component  : stacked bar — drift_category breakdown
 *   - Severity distribution         : pie / donut chart
 *   - Component-type heat-map       : component_type × product, colour = count
 *   - Top unmanaged objects         : table of high-severity findings
 *   - Drift timeline                : finding count trended over execution_ts
 */

-- ──────────────────────────────────────────────────────────────────────────────
-- Summary — finding counts grouped by product × component × drift category
-- ──────────────────────────────────────────────────────────────────────────────
WITH latest_exec AS (
  SELECT
    execution_id,
    execution_ts,
    environment,
    status,
    triggered_by,
    git_ref
  FROM `<GCP_PROJECT>.devops_reports.executions`
  WHERE report_type = 'env_drift'
    AND status      = 'success'
  QUALIFY ROW_NUMBER() OVER (ORDER BY execution_ts DESC) = 1
),

findings AS (
  SELECT
    f.execution_id,
    f.product,
    f.component_type,
    f.object_type,
    f.object_name,
    f.drift_category,
    f.source_hash,
    f.env_hash,
    f.severity,
    CASE f.severity
      WHEN 'high'   THEN 1
      WHEN 'medium' THEN 2
      WHEN 'low'    THEN 3
      WHEN 'none'   THEN 4
      ELSE               5
    END                  AS severity_sort
  FROM `<GCP_PROJECT>.devops_reports.env_drift_findings` f
  JOIN latest_exec USING (execution_id)
),

summary AS (
  SELECT
    e.execution_ts,
    e.environment,
    e.triggered_by,
    e.git_ref,
    f.product,
    f.component_type,
    f.drift_category,
    f.severity,
    f.severity_sort,
    COUNT(*)                                       AS total_findings,
    COUNT(DISTINCT f.object_name)                  AS distinct_objects,
    COUNTIF(f.source_hash IS NULL OR f.source_hash = '') AS env_only_count,
    COUNTIF(f.env_hash IS NULL   OR f.env_hash   = '') AS code_only_count,
    COUNTIF(
      f.source_hash IS NOT NULL AND f.source_hash != ''
      AND f.env_hash IS NOT NULL AND f.env_hash != ''
    )                                              AS hash_mismatch_count
  FROM latest_exec e
  JOIN findings f USING (execution_id)
  GROUP BY
    e.execution_ts, e.environment, e.triggered_by, e.git_ref,
    f.product, f.component_type, f.drift_category, f.severity, f.severity_sort
)

SELECT
  execution_ts,
  environment,
  triggered_by,
  git_ref,
  product,
  component_type,
  drift_category,
  severity,
  total_findings,
  distinct_objects,
  env_only_count       AS in_env_not_in_code,
  code_only_count      AS in_code_not_in_env,
  hash_mismatch_count  AS content_mismatch
FROM summary
ORDER BY
  severity_sort,
  total_findings DESC,
  product,
  component_type;


-- ──────────────────────────────────────────────────────────────────────────────
-- Historical Trend — finding counts across all executions (for time-series)
-- Run independently in SQL Runner or as a separate Looker tile.
-- ──────────────────────────────────────────────────────────────────────────────
/*
SELECT
  e.execution_ts,
  e.environment,
  f.product,
  f.component_type,
  f.severity,
  COUNT(*) AS total_findings
FROM `<GCP_PROJECT>.devops_reports.executions` e
JOIN `<GCP_PROJECT>.devops_reports.env_drift_findings` f USING (execution_id)
WHERE e.report_type = 'env_drift'
  AND e.status      = 'success'
GROUP BY
  e.execution_ts,
  e.environment,
  f.product,
  f.component_type,
  f.severity
ORDER BY
  e.execution_ts DESC,
  f.product,
  f.component_type,
  f.severity;
*/


-- ──────────────────────────────────────────────────────────────────────────────
-- Detail View — one row per drifted object (for drill-through)
-- Run independently in SQL Runner or as a separate Looker tile.
-- ──────────────────────────────────────────────────────────────────────────────
/*
WITH latest_exec AS (
  SELECT execution_id, execution_ts, environment, git_ref
  FROM `<GCP_PROJECT>.devops_reports.executions`
  WHERE report_type = 'env_drift'
    AND status      = 'success'
  QUALIFY ROW_NUMBER() OVER (ORDER BY execution_ts DESC) = 1
)

SELECT
  e.execution_ts,
  e.environment,
  e.git_ref,
  f.product,
  f.component_type,
  f.object_type,
  f.object_name,
  f.drift_category,
  f.severity,
  f.source_hash,
  f.env_hash
FROM `<GCP_PROJECT>.devops_reports.env_drift_findings` f
JOIN latest_exec e USING (execution_id)
ORDER BY
  CASE f.severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,
  f.product,
  f.component_type,
  f.object_name;
*/
