-- BQ view: devops_reports.file_drift_evidence_report  (Terraform/BQ DS + Tables.tf)
-- Prefer the view as the Looker Studio data source; this file is kept as reference.
/*
 * File-Content Branch Drift — File-Level Evidence Report
 *
 * Purpose : Expose one row per drifting file per run so end users can see
 *           exactly which files differ between branches, who last changed them,
 *           and when — enabling targeted remediation.
 *
 * Tables  : devops_reports.executions
 *           devops_reports.branch_drift_evidence
 *
 * Usage   : Connect Looker Studio directly to the file_drift_evidence_report
 *           BQ view.  Add Filter Controls on run_date (dropdown) and
 *           drift_direction (dropdown) to narrow the view.
 *           Set run_date as the "Date range dimension" on each chart and add a
 *           Date Range Control to the page. Do NOT check "Enable date range
 *           parameters" — that option is only available in Custom Query mode.
 *
 * Suggested dashboard tiles:
 *   - Main table  : repo / drift_direction / file_path / change_label /
 *                   last_author / last_changed_at  (one row per drifting file)
 *   - Bar chart   : count of files by change_label per repo (stacked)
 *   - Scorecards  : total files, files_added, files_modified, files_deleted
 *   - Filters     : run_date / drift_direction / repo
 */

WITH latest_exec AS (
  SELECT
    execution_id,
    execution_ts,
    DATE(execution_ts, 'Europe/Berlin') AS run_date,
    ROW_NUMBER() OVER (
      PARTITION BY DATE(execution_ts, 'Europe/Berlin')
      ORDER BY execution_ts DESC
    )                                   AS run_number,
    environment,
    triggered_by
  FROM `tefde-gcp-fastoss-dev.devops_reports.executions`
  WHERE report_type = 'file_drift'
    AND status      = 'success'
    AND status      = 'success'
)

SELECT
  e.run_date,
  e.run_number,
  e.execution_ts,
  e.environment,
  e.triggered_by,
  ev.repo,
  ev.discrepancy,
  -- Human-readable drift direction: "production differs from test"
  CONCAT(
    SPLIT(ev.discrepancy, '_not_in_')[OFFSET(0)],
    ' differs from ',
    SPLIT(ev.discrepancy, '_not_in_')[OFFSET(1)]
  )                                     AS drift_direction,
  ev.file_path,
  -- Human-readable change label for dashboard display and conditional formatting
  CASE UPPER(ev.change_type)
    WHEN 'A' THEN 'added'
    WHEN 'M' THEN 'modified'
    WHEN 'D' THEN 'deleted'
    ELSE          'other'
  END                                   AS change_label,
  ev.change_type                        AS raw_change_type,
  ev.author                             AS last_author,
  ev.commit_date                        AS last_changed_at,
  ev.commit_sha                         AS last_commit_sha,
  ev.problem_statement
FROM `tefde-gcp-fastoss-dev.devops_reports.branch_drift_evidence` ev
JOIN latest_exec e USING (execution_id)
WHERE ev.drift_type = 'content'
  AND ev.file_path  IS NOT NULL
ORDER BY
  e.run_date        DESC,
  e.run_number,
  ev.repo,
  ev.discrepancy,
  ev.file_path;
