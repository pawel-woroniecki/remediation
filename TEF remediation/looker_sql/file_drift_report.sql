/*
 * File-Content-Based Branch Drift Report
 *
 * Purpose : Identify files whose content differs between branches, using
 *           git diff (merge-base or direct mode) to detect content-level
 *           drift regardless of commit history.
 * Tables  : devops_reports.executions
 *           devops_reports.branch_drift_kpis
 *           devops_reports.branch_drift_evidence
 * Usage   : Replace <GCP_PROJECT> with your GCP project ID.
 *           In Looker, register as a native derived table or run via SQL Runner.
 *           In Looker Studio, use as a Custom Query data source.
 *
 * Suggested dashboard tiles:
 *   - File change-type breakdown : added / modified / deleted by repo (stacked bar)
 *   - Most drifted repos         : unique_files DESC
 *   - Hot files                  : file paths appearing most frequently across repos
 *   - Severity over time         : trend of unique_files per execution
 */

-- ──────────────────────────────────────────────────────────────────────────────
-- KPI Summary — one row per repo × drift direction (latest successful run)
-- ──────────────────────────────────────────────────────────────────────────────
WITH latest_exec AS (
  SELECT
    execution_id,
    execution_ts,
    environment,
    status,
    triggered_by
  FROM `<GCP_PROJECT>.devops_reports.executions`
  WHERE report_type = 'file_drift'
    AND status      = 'success'
  QUALIFY ROW_NUMBER() OVER (ORDER BY execution_ts DESC) = 1
),

kpi_summary AS (
  SELECT
    e.execution_ts,
    e.environment,
    e.triggered_by,
    k.repo,
    k.left_branch,
    k.right_branch,
    CONCAT(
      REGEXP_EXTRACT(k.right_branch, r'origin/(.+)'),
      ' differs from ',
      REGEXP_EXTRACT(k.left_branch,  r'origin/(.+)')
    )                            AS drift_direction,
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
  FROM `<GCP_PROJECT>.devops_reports.branch_drift_kpis` k
  JOIN latest_exec e USING (execution_id)
  WHERE k.drift_type = 'content'
    AND k.status     = 'ok'
),

-- Aggregate evidence counts and change-type breakdown per repo × discrepancy.
evidence_agg AS (
  SELECT
    ev.execution_id,
    ev.repo,
    ev.discrepancy,
    COUNT(DISTINCT ev.file_path)                                    AS distinct_files,
    COUNTIF(UPPER(ev.change_type) = 'A')                           AS files_added,
    COUNTIF(UPPER(ev.change_type) = 'M')                           AS files_modified,
    COUNTIF(UPPER(ev.change_type) = 'D')                           AS files_deleted,
    COUNTIF(ev.change_type NOT IN ('A','M','D') OR ev.change_type IS NULL) AS files_other,
    COUNT(DISTINCT ev.author)                                       AS distinct_authors,
    MIN(ev.commit_date)                                             AS earliest_change_date,
    MAX(ev.commit_date)                                             AS latest_change_date
  FROM `<GCP_PROJECT>.devops_reports.branch_drift_evidence` ev
  JOIN latest_exec USING (execution_id)
  WHERE ev.drift_type = 'content'
  GROUP BY
    ev.execution_id,
    ev.repo,
    ev.discrepancy
)

SELECT
  ks.execution_ts,
  ks.environment,
  ks.triggered_by,
  ks.repo,
  ks.drift_direction,
  ks.left_branch,
  ks.right_branch,
  ks.comparison_mode,
  ks.unique_commits,
  ks.unique_files,
  ks.severity,
  ks.branch_status,
  ea.distinct_authors,
  ea.files_added,
  ea.files_modified,
  ea.files_deleted,
  ea.files_other,
  ea.earliest_change_date,
  ea.latest_change_date
FROM kpi_summary ks
LEFT JOIN evidence_agg ea
  ON  ea.repo        = ks.repo
  AND ea.discrepancy = CONCAT(
        REGEXP_EXTRACT(ks.right_branch, r'origin/(.+)'), '_not_in_',
        REGEXP_EXTRACT(ks.left_branch,  r'origin/(.+)')
      )
ORDER BY
  ks.severity_sort,
  ks.unique_files DESC,
  ks.repo,
  ks.left_branch;


-- ──────────────────────────────────────────────────────────────────────────────
-- File-Level Evidence — one row per repo × file (for drill-through)
-- Run independently in SQL Runner or as a separate Looker tile.
-- ──────────────────────────────────────────────────────────────────────────────
/*
WITH latest_exec AS (
  SELECT execution_id, execution_ts, environment
  FROM `<GCP_PROJECT>.devops_reports.executions`
  WHERE report_type = 'file_drift'
    AND status      = 'success'
  QUALIFY ROW_NUMBER() OVER (ORDER BY execution_ts DESC) = 1
)

SELECT
  e.execution_ts,
  e.environment,
  ev.repo,
  ev.discrepancy          AS drift_direction,
  ev.file_path,
  ev.change_type,
  ev.author               AS last_author,
  ev.commit_sha           AS last_commit_sha,
  ev.commit_date          AS last_commit_date,
  ev.problem_statement
FROM `<GCP_PROJECT>.devops_reports.branch_drift_evidence` ev
JOIN latest_exec e USING (execution_id)
WHERE ev.drift_type = 'content'
ORDER BY
  ev.repo,
  ev.discrepancy,
  ev.file_path;
*/
