-- BQ view: devops_reports.commit_drift_report  (Terraform/BQ DS + Tables.tf)
-- Prefer the view as the Looker Studio data source; this file is kept as reference.
/*
 * Commit-Based Branch Drift Report
 *
 * Purpose : Identify commits present in one branch but absent in another,
 *           indicating un-merged cherry-picks or divergent branch histories.
 * Tables  : devops_reports.executions
 *           devops_reports.branch_drift_kpis
 *           devops_reports.branch_drift_evidence
 * Usage   : Connect Looker Studio directly to the commit_drift_report BQ view.
 *           This SQL is kept as reference; it does NOT include run_number.
 *
 * Suggested dashboard tiles:
 *   - Severity heat-map  : repo × drift direction, colour = severity
 *   - Top drifted repos  : bar chart — unique_commits DESC
 *   - Author leaderboard : commits by author that are out-of-sync
 *   - Drift timeline     : unique_commits trended over execution_ts
 */

-- ──────────────────────────────────────────────────────────────────────────────
-- KPI Summary — one row per repo × drift direction × run (last 90 days)
-- In Looker Studio: use a Filter control (dropdown) on run_date to pick one day.
-- "Enable date range parameters" must be UNCHECKED on this data source.
-- ──────────────────────────────────────────────────────────────────────────────
WITH latest_exec AS (
  SELECT
    execution_id,
    execution_ts,
    DATE(execution_ts, 'Europe/Berlin') AS run_date,
    environment,
    status,
    triggered_by
  FROM `tefde-gcp-fastoss-dev.devops_reports.executions`
  WHERE report_type = 'commit_drift'
    AND status      = 'success'
    AND execution_ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
),

kpi_summary AS (
  SELECT
    e.execution_id,
    e.run_date,
    e.execution_ts,
    e.environment,
    e.triggered_by,
    k.repo,
    k.left_branch,
    k.right_branch,
    CASE CONCAT(REGEXP_EXTRACT(k.right_branch, r'origin/(.+)'),
                ' not in ',
                REGEXP_EXTRACT(k.left_branch,  r'origin/(.+)'))
      WHEN 'test not in master'       THEN '⚠ test not in master'
      WHEN 'production not in test'   THEN '⚠ production not in test'
      WHEN 'production not in master' THEN '⚠ production not in master'
      ELSE CONCAT(REGEXP_EXTRACT(k.right_branch, r'origin/(.+)'),
                  ' not in ',
                  REGEXP_EXTRACT(k.left_branch,  r'origin/(.+)'))
    END                          AS drift_direction,
    k.unique_commits,
    k.unique_files,
    k.severity,
    k.status                     AS branch_status,
    k.comparison_mode,
    CASE k.severity
      WHEN 'high'   THEN 1
      WHEN 'medium' THEN 2
      WHEN 'low'    THEN 3
      WHEN 'none'   THEN 4
      ELSE               5
    END                          AS severity_sort
  FROM `tefde-gcp-fastoss-dev.devops_reports.branch_drift_kpis` k
  JOIN latest_exec e USING (execution_id)
  WHERE k.drift_type = 'commit'
    AND k.status     = 'ok'
),

-- Aggregate evidence counts per repo × discrepancy to enrich the KPI rows.
evidence_agg AS (
  SELECT
    ev.execution_id,
    ev.repo,
    ev.discrepancy,
    COUNT(DISTINCT ev.commit_sha) AS distinct_commits,
    COUNT(DISTINCT ev.author)     AS distinct_authors,
    COUNT(DISTINCT ev.file_path)  AS distinct_files,
    MIN(ev.commit_date)           AS earliest_commit_date,
    MAX(ev.commit_date)           AS latest_commit_date
  FROM `tefde-gcp-fastoss-dev.devops_reports.branch_drift_evidence` ev
  JOIN latest_exec USING (execution_id)
  WHERE ev.drift_type = 'commit'
  GROUP BY
    ev.execution_id,
    ev.repo,
    ev.discrepancy
)

SELECT
  ks.run_date,
  ks.execution_ts,
  ks.environment,
  ks.triggered_by,
  ks.repo,
  ks.drift_direction,
  ks.left_branch,
  ks.right_branch,
  ks.unique_commits,
  ks.unique_files,
  ks.severity,
  ks.branch_status,
  ks.comparison_mode,
  ea.distinct_authors,
  ea.earliest_commit_date,
  ea.latest_commit_date
FROM kpi_summary ks
LEFT JOIN evidence_agg ea
  ON  ea.execution_id  = ks.execution_id
  AND ea.repo          = ks.repo
  AND ea.discrepancy   = CONCAT(
        REGEXP_EXTRACT(ks.right_branch, r'origin/(.+)'), '_not_in_',
        REGEXP_EXTRACT(ks.left_branch,  r'origin/(.+)')
      )
ORDER BY
  ks.severity_sort,
  ks.unique_commits DESC,
  ks.repo,
  ks.left_branch;


-- ──────────────────────────────────────────────────────────────────────────────
-- Detailed Evidence — one row per repo × commit × file (for drill-through)
-- Run this query independently in SQL Runner or as a separate Looker tile.
-- ──────────────────────────────────────────────────────────────────────────────
/*
WITH latest_exec AS (
  SELECT execution_id, execution_ts, environment
  FROM `tefde-gcp-fastoss-dev.devops_reports.executions`
  WHERE report_type = 'commit_drift'
    AND status      = 'success'
  QUALIFY ROW_NUMBER() OVER (ORDER BY execution_ts DESC) = 1
)

SELECT
  e.execution_ts,
  e.environment,
  ev.repo,
  ev.discrepancy         AS drift_direction,
  ev.commit_sha,
  ev.commit_date,
  ev.author,
  ev.file_path,
  ev.problem_statement
FROM `tefde-gcp-fastoss-dev.devops_reports.branch_drift_evidence` ev
JOIN latest_exec e USING (execution_id)
WHERE ev.drift_type = 'commit'
ORDER BY
  ev.repo,
  ev.discrepancy,
  ev.commit_date DESC,
  ev.commit_sha,
  ev.file_path;
*/
