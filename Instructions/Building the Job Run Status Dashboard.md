# Building the Job Run Status Dashboard in Looker Studio

This document explains how to build a dashboard that shows the overall status of each
Cloud Run job execution across all four report types. The dashboard has four statistics
tables — one per report — so a silent failure (job succeeded but processed nothing) is
immediately visible alongside hard failures.

The data comes from the `env_drift_job_summary` BigQuery view, which surfaces the
job-level summary row written by `entrypoint.sh` at the end of every `env_drift` run.

---

## Background — what the summary row tracks

At the end of every `env_drift` Cloud Run job, `entrypoint.sh` writes a single row to
`devops_reports.executions` with `project_name = '_job_summary'`. The row records:

| Column | Description |
|---|---|
| `repos_total` | Total directories found in the subgroup after cloning |
| `repos_launched` | Repos actually processed (had `.git`, not excluded by `EXCLUDE_REPOS`) |
| `repos_success` | Repos that completed without error |
| `repos_failed` | Repos that exited with a non-zero code |
| `repos_skipped` | `repos_total − repos_launched` — repos skipped (clone failed or excluded) |
| `status` | `success`, `success_with_warnings`, or `failed` |
| `duration_seconds` | Total elapsed time of the job in seconds |

**Status meanings:**

| Status | Condition |
|---|---|
| `success` | All repos were cloned, launched, and completed without error |
| `success_with_warnings` | All launched repos succeeded, but some repos had no `.git` (clone failure or excluded by config) |
| `failed` | One or more launched repos exited with a non-zero code |

The `env_drift_job_summary` view returns **one row per environment** (latest run only).

---

## Prerequisites

- `terraform apply` has been run after the `repos_total / repos_launched / repos_success /
  repos_failed` columns were added to the `executions` table and the `env_drift_job_summary`
  view was created.
- At least one `devops-reports-env-drift` Cloud Run Job execution has completed so the view
  has data.
- A `telefonica.de` Google account with read access to `tefde-gcp-fastoss-dev`.

---

## Step 1 — Create the report and connect the data source

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com) and sign in.
2. Click **Create → Report**.
3. In the data source picker choose **BigQuery**.
4. Navigate: **My Projects → `tefde-gcp-fastoss-dev` → `devops_reports` →
   `env_drift_job_summary`**.
5. Click **Add** (top right) → **Add to Report**.

Alternatively, connect via **Custom Query** if you need cross-environment history
(the view shows only the latest run per environment by default):

```sql
SELECT
  execution_id,
  execution_ts,
  environment,
  triggered_by,
  status,
  repos_total,
  repos_launched,
  repos_success,
  repos_failed,
  repos_total - repos_launched  AS repos_skipped,
  duration_seconds
FROM `tefde-gcp-fastoss-dev.devops_reports.executions`
WHERE report_type  = 'env_drift'
  AND project_name = '_job_summary'
ORDER BY execution_ts DESC
```

> **Important — "Enable date range parameters" must be unchecked.**
> When using a custom query, Looker Studio shows a checkbox labelled **"Enable date range
> parameters"** at the bottom of the query editor. Leave it **unchecked**. If it is
> checked, Looker Studio expects the query itself to contain `@DS_START_DATE` /
> `@DS_END_DATE` placeholders, and it hides the chart-level "Date range dimension" option
> — meaning the page-level date range control will have no effect on the table, even after
> you set a date dimension. With the box unchecked, Looker Studio handles date filtering
> at the chart level and the "Date range dimension" field appears correctly in the chart
> Setup panel.

Name the data source `Env Drift Job Runs`.

---

## Step 2 — Set field types

1. Click **Resource → Manage added data sources → pencil icon** on `Env Drift Job Runs`.
2. Set `status` to type **Text** (if Looker Studio auto-detects it as a metric, change it
   to a dimension).
3. Set `duration_seconds` to type **Number**, aggregation **No aggregation** if used as a
   dimension, or leave as **SUM** if used as a metric.
4. Click **Done → Close**.

---

## Step 3 — Add summary scorecards

Place four scorecard tiles across the top of the page. Each shows the latest run's values.

| Scorecard | Metric | Aggregation | Label |
|---|---|---|---|
| Total repos | `repos_total` | MAX | `Repos discovered` |
| Launched | `repos_launched` | MAX | `Repos processed` |
| Successful | `repos_success` | MAX | `Repos succeeded` |
| Failed/skipped | `repos_failed` | MAX | `Repos failed` |

> Use **MAX** aggregation because the view already returns one row per environment.
> Avoid SUM — if the date range covers multiple runs, SUM would add counts together.

Add a fifth scorecard for job duration:
- Metric: `duration_seconds`, Aggregation: MAX. Label: `Duration (s)`.

---

## Step 4 — Add a status indicator

A single-cell **Scorecard** showing the latest `status` value works well as a
headline indicator.

1. **Insert → Scorecard**.
2. Metric: `status`, Aggregation: **Max** (returns the alphabetically last value — to get
   the correct latest-run value, use the Custom Query from Step 1 with `LIMIT 1` instead).
3. Alternative: use a **Table** with one row, Dimension: `status`, and apply conditional
   formatting (see Step 6) to colour the status cell.

---

## Step 5 — Build the history table

A table showing one row per job run lets you see trends — whether the job is consistently
succeeding or intermittently producing warnings.

1. **Insert → Table**.
2. Use the **Custom Query** data source from Step 1 (not the view, so you get all
   historical rows, not just the latest).
3. **Dimensions:** `execution_ts`, `environment`, `triggered_by`, `status`,
   `repos_total`, `repos_launched`, `repos_success`, `repos_failed`,
   `repos_skipped`, `duration_seconds`
   - Keep all columns as **Dimensions** (no Metrics). This is required for the date
     range control to work — the "Date range dimension" option only appears in the
     chart Setup panel when the Metrics section is empty.
4. **Sort:** `execution_ts` descending (newest first).
5. **Rows per page:** 20–30.
6. In the **Setup** panel, set **Date range dimension** to `execution_ts`.
   This connects the table to the page-level date range control.

---

## Step 6 — Conditional formatting on the status column

Colour-code the `status` column so problems are immediately visible.

1. Select the table → **Style** tab → scroll to **Conditional formatting**.
2. Add three rules on the `status` dimension:

| Condition | Format |
|---|---|
| Text **is** `success` | Background colour `#E6F4EA` (light green), text `#1B8A00` (dark green) |
| Text **is** `success_with_warnings` | Background colour `#FFF8E1` (light amber), text `#E65100` (orange) |
| Text **is** `failed` | Background colour `#FDECEA` (light red), text `#C62828` (dark red), **Bold** |

---

## Step 7 — Add filter controls

Insert these controls above the table and scorecards:

### Date range control

1. **Insert → Date range control**.
2. Default: **Last 30 days**.
3. Bind to field `execution_ts`.

### Environment dropdown (if you run reports against multiple environments)

1. **Insert → Filter control**.
2. Field: `environment`. Type: **Drop-down list**. Label: `Environment`.

> To make all controls apply to every chart on the page: select each control → right
> panel → **Filter** section → confirm **All charts on this page** is selected.

---

## Step 8 — Share the dashboard

1. Click **Share** (top right).
2. Add the team or Google Group (`@telefonica.de`).
3. For organisation-wide access without individual GCP permissions, follow the **Step 0 —
   One-time GCP setup for Service Account Credentials** instructions in
   `Instructions/Building the Looker Studio Dashboards.md`.

---

## Backfilling historical rows

Two separate backfill steps are needed after the feature is first deployed:

### Step 1 — Insert missing `_job_summary` rows for all historical runs

The `_job_summary` row (one per job run) is only written by the entrypoint after the
feature is deployed. Runs before that deployment have per-repo rows in `executions` but
no summary row, so the Job Run Status table is blank for those dates.

Run the SQL below **once** in BigQuery console (replace `<project>` with
`tefde-gcp-fastoss-dev`). The `AND execution_ts < MIN(_job_summary)` guard prevents
inserting duplicates for runs that already have a summary row, so it is safe to re-run:

```sql
INSERT INTO `<project>.devops_reports.executions`
  (execution_id, report_type, project_name, execution_ts, environment,
   git_ref, source_mode, triggered_by, status, duration_seconds, gcs_path,
   repos_total, repos_launched, repos_success, repos_failed)

WITH
per_repo AS (
  SELECT *
  FROM `<project>.devops_reports.executions`
  WHERE report_type   = 'env_drift'
    AND project_name != '_job_summary'
    AND execution_ts < (
      SELECT MIN(execution_ts)
      FROM `<project>.devops_reports.executions`
      WHERE report_type  = 'env_drift'
        AND project_name = '_job_summary'
    )
),
with_lag AS (
  SELECT *,
    LAG(execution_ts) OVER (
      PARTITION BY environment, DATE(execution_ts, 'Europe/Berlin')
      ORDER BY execution_ts
    ) AS lag_ts
  FROM per_repo
),
grouped AS (
  SELECT *,
    SUM(
      CASE
        WHEN lag_ts IS NULL
          OR TIMESTAMP_DIFF(execution_ts, lag_ts, MINUTE) > 5
        THEN 1 ELSE 0
      END
    ) OVER (
      PARTITION BY environment, DATE(execution_ts, 'Europe/Berlin')
      ORDER BY execution_ts
    ) AS run_group
  FROM with_lag
)
SELECT
  GENERATE_UUID()                                               AS execution_id,
  'env_drift'                                                   AS report_type,
  '_job_summary'                                                AS project_name,
  MIN(execution_ts)                                             AS execution_ts,
  environment,
  ANY_VALUE(git_ref)                                            AS git_ref,
  ANY_VALUE(source_mode)                                        AS source_mode,
  ANY_VALUE(triggered_by)                                       AS triggered_by,
  IF(COUNTIF(status = 'failed') > 0, 'failed', 'success')      AS status,
  TIMESTAMP_DIFF(MAX(execution_ts), MIN(execution_ts), SECOND)  AS duration_seconds,
  CAST(NULL AS STRING)                                          AS gcs_path,
  COUNT(*)                                                      AS repos_total,
  COUNT(*)                                                      AS repos_launched,
  COUNTIF(status IN ('success', 'skipped'))                     AS repos_success,
  COUNTIF(status = 'failed')                                    AS repos_failed
FROM grouped
GROUP BY environment, DATE(execution_ts, 'Europe/Berlin'), run_group
```

Verify the result:

```sql
SELECT DATE(execution_ts, 'Europe/Berlin') AS run_date, environment, COUNT(*) AS job_runs
FROM `<project>.devops_reports.executions`
WHERE report_type = 'env_drift' AND project_name = '_job_summary'
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

Each date should show one row per job run per environment. `repos_skipped` will be 0 for
backfilled rows because the per-repo records don't capture clone failures — only runs after
deployment will have an accurate `repos_skipped` count.

### Step 2 — Set repo counts on historical per-repo rows

The `repos_total / repos_launched / repos_success / repos_failed` columns are NULL for
per-repo rows written before deployment. Run the UPDATE below (replace `<project>` and `42`
with the actual repo count at the time):

```sql
-- Historical success runs
UPDATE `<project>.devops_reports.executions`
SET repos_total    = 42,
    repos_launched = 42,
    repos_success  = 42,
    repos_failed   = 0
WHERE report_type   = 'env_drift'
  AND project_name != '_job_summary'
  AND status        = 'success'
  AND repos_total IS NULL;

-- Historical failed runs
UPDATE `<project>.devops_reports.executions`
SET repos_total    = 42,
    repos_launched = 42,
    repos_success  = 0,
    repos_failed   = 42
WHERE report_type   = 'env_drift'
  AND project_name != '_job_summary'
  AND status        = 'failed'
  AND repos_total IS NULL;
```

The `AND repos_total IS NULL` guard makes both statements safe to re-run.

> **Note:** Step 2 uses fixed approximations. Historical per-repo rows will not show
> `success_with_warnings` status. Only runs after deployment will have accurate counts.

---

## Data source field reference

| Field | Type | Description |
|---|---|---|
| `execution_id` | Dimension | Unique ID for this Cloud Run job execution |
| `execution_ts` | Date dimension | Job start timestamp — use as the date range filter field |
| `environment` | Dimension | Target environment (`prod`, `test`, `dev`) |
| `triggered_by` | Dimension | Who or what triggered the job (`manual`, scheduler name, etc.) |
| `status` | Dimension | `success` / `success_with_warnings` / `failed` |
| `repos_total` | Metric | Total repo directories discovered in subgroup after cloning |
| `repos_launched` | Metric | Repos actually processed (had `.git`, not excluded) |
| `repos_success` | Metric | Repos that completed without error |
| `repos_failed` | Metric | Repos that exited with a non-zero code |
| `repos_skipped` | Metric | `repos_total − repos_launched` (clone failures + EXCLUDE_REPOS matches) |
| `duration_seconds` | Metric | Total elapsed time of the job in seconds |

---

---

---

# Extending the dashboard — Commit Drift statistics

The `commit_drift_job_summary` BigQuery view provides per-run statistics for the
`devops-reports-commit-drift` Cloud Run Job. Unlike env_drift, this view derives its
counts by joining the `executions` table with `branch_drift_kpis` — no summary row is
written by the script, so the counts are aggregated in the view itself.

## Key signal — repos_processed = 0

If the job reports `status = success` but `repos_processed = 0`, the GitLab clone loop
silently processed nothing. This is the most dangerous failure mode: the dashboard shows
green but all data is stale. Always check `repos_processed` first.

## Step 1 — Add the commit drift data source

1. In the existing Job Run Status report, click **Resource → Manage added data sources →
   Add a data source**.
2. Choose **BigQuery**.
3. Navigate: **My Projects → `tefde-gcp-fastoss-dev` → `devops_reports` →
   `commit_drift_job_summary`**.
4. Click **Add → Add to Report**.
5. Name the data source `Commit Drift Job Runs`.

Alternatively, use a Custom Query to get the full history (the view returns all rows):

```sql
SELECT
  execution_id,
  execution_ts,
  triggered_by,
  status,
  duration_seconds,
  repos_processed,
  repos_ok,
  repos_missing_branch,
  repos_with_drift,
  repos_high_severity,
  total_commits_in_drift
FROM `tefde-gcp-fastoss-dev.devops_reports.commit_drift_job_summary`
ORDER BY execution_ts DESC
```

> Leave **"Enable date range parameters" unchecked** (same as env_drift — see Step 1 in
> the env_drift section above).

## Step 2 — Set field types

1. **Resource → Manage added data sources → pencil icon** on `Commit Drift Job Runs`.
2. Set `status` to type **Text** / Dimension.
3. Set all count columns (`repos_processed`, `repos_ok`, `repos_missing_branch`,
   `repos_with_drift`, `repos_high_severity`, `total_commits_in_drift`) to type
   **Number**, aggregation **No aggregation** (or **MAX** if used as scorecards).
4. Click **Done → Close**.

## Step 3 — Add the statistics table

1. **Insert → Table**.
2. Data source: `Commit Drift Job Runs`.
3. **Dimensions** (keep all as dimensions, no metrics):
   `execution_ts`, `triggered_by`, `status`, `repos_processed`, `repos_ok`,
   `repos_missing_branch`, `repos_with_drift`, `repos_high_severity`,
   `total_commits_in_drift`, `duration_seconds`
4. **Sort:** `execution_ts` descending.
5. **Setup panel → Date range dimension:** `execution_ts`.

## Step 4 — Conditional formatting

Add two rules on the `repos_processed` column to highlight the silent-failure case:

| Condition | Format |
|---|---|
| `repos_processed` **=** `0` | Background `#FDECEA` (light red), text `#C62828` (dark red), **Bold** |
| `repos_processed` **>** `0` | Background `#E6F4EA` (light green), text `#1B8A00` (dark green) |

Add the same status colour rules as env_drift (success / failed — commit drift does not
produce `success_with_warnings`).

## Step 5 — Add a date range control

Re-use the page-level date range control already on the page, or insert a new one bound
to `execution_ts` and set it to apply to all charts on the page.

## Data source field reference

| Field | Type | Description |
|---|---|---|
| `execution_id` | Dimension | Unique ID for this Cloud Run job execution |
| `execution_ts` | Date dimension | Job start timestamp — use as the date range filter field |
| `triggered_by` | Dimension | Who triggered the job |
| `status` | Dimension | `success` or `failed` |
| `duration_seconds` | Metric | Total elapsed time of the job in seconds |
| `repos_processed` | Metric | Repositories processed — **0 = silent failure** |
| `repos_ok` | Metric | Repos where all branch comparisons found no drift |
| `repos_missing_branch` | Metric | Repos where one or more monitored branches do not exist |
| `repos_with_drift` | Metric | Repos with at least one commit difference (any severity) |
| `repos_high_severity` | Metric | Repos with high-severity commit drift |
| `total_commits_in_drift` | Metric | Total commits present in one branch but missing from another |

---

---

# Extending the dashboard — File Drift statistics

The `file_drift_job_summary` view follows the same pattern as commit drift, but uses
`drift_type = 'content'` rows from `branch_drift_kpis` and counts files instead of
commits. It adds a `repos_with_error` column that is not present in commit drift.

## Step 1 — Add the file drift data source

1. **Resource → Manage added data sources → Add a data source → BigQuery**.
2. Navigate to `tefde-gcp-fastoss-dev → devops_reports → file_drift_job_summary`.
3. Name the data source `File Drift Job Runs`.

Custom Query alternative:

```sql
SELECT
  execution_id,
  execution_ts,
  triggered_by,
  status,
  duration_seconds,
  repos_processed,
  repos_ok,
  repos_missing_branch,
  repos_with_error,
  repos_with_drift,
  repos_high_severity,
  total_files_in_drift
FROM `tefde-gcp-fastoss-dev.devops_reports.file_drift_job_summary`
ORDER BY execution_ts DESC
```

## Step 2 — Add the statistics table

Same steps as commit drift (Steps 2–5 above), with these differences:

- Replace `total_commits_in_drift` with `total_files_in_drift` in the dimension list.
- Add `repos_with_error` as an additional dimension.
- Add a conditional formatting rule on `repos_with_error`:

| Condition | Format |
|---|---|
| `repos_with_error` **>** `0` | Background `#FFF8E1` (light amber), text `#E65100` (orange) |

## Data source field reference

| Field | Type | Description |
|---|---|---|
| `execution_id` | Dimension | Unique ID for this Cloud Run job execution |
| `execution_ts` | Date dimension | Job start timestamp |
| `triggered_by` | Dimension | Who triggered the job |
| `status` | Dimension | `success` or `failed` |
| `duration_seconds` | Metric | Total elapsed time of the job in seconds |
| `repos_processed` | Metric | Repositories processed — **0 = silent failure** |
| `repos_ok` | Metric | Repos with no file differences |
| `repos_missing_branch` | Metric | Repos where a monitored branch does not exist |
| `repos_with_error` | Metric | Repos where the diff comparison returned an error |
| `repos_with_drift` | Metric | Repos with at least one file difference |
| `repos_high_severity` | Metric | Repos with high-severity file drift |
| `total_files_in_drift` | Metric | Total files differing across all repos and directions |

---

---

# Extending the dashboard — Orphan Datasets statistics

The `orphan_datasets_job_summary` view joins `executions` (report_type = `orphan_datasets`)
with the `orphan_datasets` table to show per-run orphan counts.

> **Note on coverage:** The view shows counts of *orphan* datasets found, not the total
> number of datasets scanned. The total-scanned figure is computed in the script but not
> currently persisted to BigQuery. Until that is added, the "did it do anything" check
> relies on `status` rather than a `datasets_processed` counter. A sharp drop to 0 orphans
> should be verified manually if no cleanup was planned.

## Step 1 — Add the orphan datasets data source

1. **Resource → Manage added data sources → Add a data source → BigQuery**.
2. Navigate to `tefde-gcp-fastoss-dev → devops_reports → orphan_datasets_job_summary`.
3. Name the data source `Orphan Datasets Job Runs`.

Custom Query alternative:

```sql
SELECT
  execution_id,
  execution_ts,
  triggered_by,
  status,
  duration_seconds,
  orphan_datasets_found,
  total_objects_in_orphans,
  high_risk_datasets
FROM `tefde-gcp-fastoss-dev.devops_reports.orphan_datasets_job_summary`
ORDER BY execution_ts DESC
```

## Step 2 — Add the statistics table

1. **Insert → Table**, data source: `Orphan Datasets Job Runs`.
2. **Dimensions:** `execution_ts`, `triggered_by`, `status`, `orphan_datasets_found`,
   `high_risk_datasets`, `total_objects_in_orphans`, `duration_seconds`.
3. **Sort:** `execution_ts` descending.
4. **Setup panel → Date range dimension:** `execution_ts`.

## Step 3 — Conditional formatting

| Column | Condition | Format |
|---|---|---|
| `status` | Text **is** `success` | Background `#E6F4EA`, text `#1B8A00` |
| `status` | Text **is** `failed` | Background `#FDECEA`, text `#C62828`, **Bold** |
| `high_risk_datasets` | Value **>** `0` | Background `#FDECEA`, text `#C62828`, **Bold** |
| `orphan_datasets_found` | Value **=** `0` | Background `#FFF8E1`, text `#E65100` — verify this is a genuine zero, not a scan failure |

## Step 4 — Add a scorecard for high-risk datasets

A single scorecard prominently showing `high_risk_datasets` (MAX aggregation) for the
latest run makes the most critical metric visible without opening the table:

1. **Insert → Scorecard**.
2. Metric: `high_risk_datasets`, Aggregation: **MAX**.
3. Label: `High-risk orphans today`.
4. In the **Style** tab, set a conditional colour: if the value is > 0 use red text.

## Data source field reference

| Field | Type | Description |
|---|---|---|
| `execution_id` | Dimension | Unique ID for this Cloud Run job execution |
| `execution_ts` | Date dimension | Job start timestamp |
| `triggered_by` | Dimension | Who triggered the job |
| `status` | Dimension | `success` or `failed` |
| `duration_seconds` | Metric | Total elapsed time of the job in seconds |
| `orphan_datasets_found` | Metric | Distinct orphan datasets detected in this run |
| `total_objects_in_orphans` | Metric | Total tables/views across all orphan datasets |
| `high_risk_datasets` | Metric | Orphan datasets with risk_score ≥ 2 |

---

## Related

- `Instructions/Building the Looker Studio Dashboards.md` — full multi-page dashboard guide and one-time GCP service account setup
- `Instructions/Building the Env Drift Summary Dashboard.md` — per-repository env-drift findings table
- `Instructions/Building the Management Dashboard.md` — executive red/green health grid
- `TEF remediation/Terraform/BQ DS + Tables.tf` — all four job-summary view definitions (`env_drift_job_summary`, `commit_drift_job_summary`, `file_drift_job_summary`, `orphan_datasets_job_summary`)
