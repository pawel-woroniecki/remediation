# Building the Job Run Status Dashboard in Looker Studio

This document explains how to build a dashboard that shows the overall status of each
`env_drift` Cloud Run job execution — how many repositories were processed, how many
succeeded, and whether any were skipped because they failed to clone.

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
3. **Dimensions:** `execution_ts`, `environment`, `triggered_by`, `status`
4. **Metrics:** `repos_total`, `repos_launched`, `repos_success`, `repos_failed`,
   `repos_skipped`, `duration_seconds`
5. **Sort:** `execution_ts` descending (newest first).
6. **Rows per page:** 20–30.

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

The new `repos_total / repos_launched / repos_success / repos_failed` columns are NULL
for execution rows written before this feature was deployed. After `terraform apply`, run
the following BigQuery DML to populate historical rows with approximate values (replace
`<reporting_project>` with `tefde-gcp-fastoss-dev` and `42` with the actual current repo
count):

```sql
-- Historical success runs
UPDATE `<reporting_project>.devops_reports.executions`
SET repos_total    = 42,
    repos_launched = 42,
    repos_success  = 42,
    repos_failed   = 0
WHERE report_type   = 'env_drift'
  AND project_name != '_job_summary'
  AND status        = 'success'
  AND repos_total IS NULL;

-- Historical failed runs
UPDATE `<reporting_project>.devops_reports.executions`
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

> **Note:** The backfill uses fixed approximations (42 repos, all success or all failed).
> These historical rows will not show `success_with_warnings` status. Only runs after
> deployment will have accurate per-category counts.

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

## Related

- `Instructions/Building the Looker Studio Dashboards.md` — full multi-page dashboard guide and one-time GCP service account setup
- `Instructions/Building the Env Drift Summary Dashboard.md` — per-repository env-drift findings table
- `Instructions/Building the Management Dashboard.md` — executive red/green health grid
- `TEF remediation/Terraform/BQ DS + Tables.tf` — `env_drift_job_summary` view definition
- `TEF remediation/entrypoint.sh` — `env_drift` case that writes the job-level summary row
