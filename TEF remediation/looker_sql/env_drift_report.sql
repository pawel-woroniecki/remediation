/*
 * Environment vs. Code Drift Report
 *
 * Purpose : Show discrepancies between what is defined in source code (git)
 *           and what is actually deployed in GCP environments.  Surfaces
 *           objects that exist in an environment but have no code definition
 *           (shadow resources) and code objects not yet deployed.
 * Tables  : devops_reports.executions
 *           devops_reports.env_drift_findings
 * Usage   : Replace tefde-gcp-fastoss-dev with your GCP project ID.
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
WITH latest_findings AS (
  -- Each repo runs as a separate subprocess with its own execution_id.
  -- PARTITION BY f.product keeps the most recent successful execution per repo
  -- so all repos appear, not just whichever one wrote its executions row last.
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
    END                  AS severity_sort,
    e.execution_ts,
    e.environment,
    e.triggered_by,
    e.git_ref
  FROM `tefde-gcp-fastoss-dev.devops_reports.env_drift_findings` f
  JOIN `tefde-gcp-fastoss-dev.devops_reports.executions` e USING (execution_id)
  WHERE e.report_type = 'env_drift'
    AND e.status      = 'success'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY f.product ORDER BY e.execution_ts DESC) = 1
),

summary AS (
  SELECT
    execution_ts,
    environment,
    triggered_by,
    git_ref,
    product,
    component_type,
    drift_category,
    severity,
    severity_sort,
    COUNT(*)                                       AS total_findings,
    COUNT(DISTINCT object_name)                    AS distinct_objects,
    COUNTIF(source_hash IS NULL OR source_hash = '') AS env_only_count,
    COUNTIF(env_hash IS NULL   OR env_hash   = '') AS code_only_count,
    COUNTIF(
      source_hash IS NOT NULL AND source_hash != ''
      AND env_hash IS NOT NULL AND env_hash != ''
    )                                              AS hash_mismatch_count
  FROM latest_findings
  GROUP BY
    execution_ts, environment, triggered_by, git_ref,
    product, component_type, drift_category, severity, severity_sort
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
FROM `tefde-gcp-fastoss-dev.devops_reports.executions` e
JOIN `tefde-gcp-fastoss-dev.devops_reports.env_drift_findings` f USING (execution_id)
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
WITH latest_findings AS (
  SELECT
    f.execution_id,
    f.product,
    f.component_type,
    f.object_type,
    f.object_name,
    f.drift_category,
    f.severity,
    f.source_hash,
    f.env_hash,
    e.execution_ts,
    e.environment,
    e.git_ref
  FROM `tefde-gcp-fastoss-dev.devops_reports.env_drift_findings` f
  JOIN `tefde-gcp-fastoss-dev.devops_reports.executions` e USING (execution_id)
  WHERE e.report_type = 'env_drift'
    AND e.status      = 'success'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY f.product ORDER BY e.execution_ts DESC) = 1
)

SELECT
  execution_ts,
  environment,
  git_ref,
  product,
  component_type,
  object_type,
  object_name,
  drift_category,
  severity,
  source_hash,
  env_hash
FROM latest_findings
ORDER BY
  CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,
  product,
  component_type,
  object_name;
*/
