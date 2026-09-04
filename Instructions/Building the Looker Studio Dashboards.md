# Building the Looker Studio Dashboards — Step-by-Step Guide

This document walks through building a 4-page Looker Studio report on top of the
`devops_reports` BigQuery dataset: an Overview/Health page plus one page per report type. It
uses the queries already written in `looker_sql/` and the `execution_daily_summary` view.

The dashboard uses Service Account Credentials so it remains accessible after any individual
leaves the organisation. Complete the one-time GCP setup in Step 0 before building the report.

---

## Prerequisites

- A `telefonica.de` Google account with permission to edit Looker Studio reports and to run
  `gcloud` commands against `tefde-gcp-resvadm-prod-backend`.
- The files in `looker_sql/`: `commit_drift_report.sql`, `file_drift_report.sql`,
  `env_drift_report.sql`, `orphan_datasets_report.sql`. Each already has the GCP project ID
  filled in (`tefde-gcp-fastoss-dev`).

---

## Step 0 — One-time GCP setup for Service Account Credentials

This step is performed once per Looker Studio report. It grants Looker Studio's service agent
the right to impersonate `devops-reports-runner` so the dashboard works for all viewers
regardless of their personal GCP access.

### 0.1 — Enable the Looker Studio API

In the GCP Console, enable the Looker Studio API in the reporting project:

```
https://console.cloud.google.com/apis/library/datastudio.googleapis.com?project=tefde-gcp-fastoss-dev
```

Click **Enable** (takes a few seconds).

### 0.2 — Get the project number

```bash
gcloud projects describe tefde-gcp-fastoss-dev --format="value(projectNumber)"
```

Note the number — call it `PROJECT_NUMBER` in the commands below.

### 0.3 — Grant Token Creator on the runner service account

```bash
gcloud iam service-accounts add-iam-policy-binding \
  devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com \
  --member="serviceAccount:service-PROJECT_NUMBER@gcp-sa-datastudio.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project=tefde-gcp-resvadm-prod-backend
```

This allows Looker Studio's own service agent to generate tokens as `devops-reports-runner`,
which has BigQuery read access to `tefde-gcp-fastoss-dev.devops_reports`.

### 0.4 — Link the Looker Studio report to the GCP project

After creating the report in Step 1:

1. In the report editor → **File → Report settings**.
2. Scroll to **Google Cloud project** and enter `tefde-gcp-fastoss-dev`.
3. Click **Save**.

This step makes Looker Studio use the service agent from the project above (whose Token
Creator permission you just granted).

### 0.5 — Set Service Account Credentials on each data source

Whenever you add a new data source (Steps 1–5 below):

1. Open **Resource → Manage added data sources** → click the pencil icon on the source.
2. Click **Edit connection** → **Update data credentials**.
3. Select **Service Account Credentials**.
4. Enter `devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com`.
5. Click **Update**.

The error "missing iam.serviceAccount.getAccessToken" will not appear if Step 0.3 was
completed first.

---

## Step 1 — Create the report and the first data source

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com) and sign in.
2. Click **Create → Report**.
3. In the data source picker, choose the **BigQuery** connector.
4. Select **My Projects** → project `tefde-gcp-fastoss-dev` → dataset `devops_reports` → table
   `execution_daily_summary`.
5. Click **Add** in the top right, then **Add to Report** when prompted.

This creates the report and wires up the first data source (used for the Overview page).

---

## Step 2 — Build Page 1: Overview / Health

This page uses the `execution_daily_summary` data source added in Step 1.

1. Rename the page: double-click **Page 1** at the bottom and type `Overview`.
2. **Scorecard — success rate today**
   - Insert → Scorecard.
   - Metric: `success_rate`.
   - Add a filter: `execution_date` = today (use a default date range control instead — see
     Step 6 — rather than hardcoding).
3. **Scorecard — total executions today**
   - Insert → Scorecard. Metric: `total_count` (set aggregation to SUM).
4. **Stacked bar — success/failure trend**
   - Insert → Bar chart (stacked).
   - Dimension: `execution_date`.
   - Breakdown dimension: `report_type`.
   - Metric: `success_count` and `failure_count` (add both as metrics).
5. **Table — most recent execution per report**
   - Add a second data source: **Resource → Manage added data sources → Add a data source →
     BigQuery → Custom Query**. Project: `tefde-gcp-fastoss-dev`. Query:
     ```sql
     SELECT execution_id, report_type, execution_ts, status, triggered_by, duration_seconds, gcs_path
     FROM `tefde-gcp-fastoss-dev.devops_reports.executions`
     QUALIFY ROW_NUMBER() OVER (PARTITION BY report_type ORDER BY execution_ts DESC) = 1
     ```
   - Insert → Table, using this new data source.
   - Columns: `report_type`, `execution_ts`, `status`, `triggered_by`, `duration_seconds`,
     `gcs_path`.

---

## Step 3 — Build Page 2: Branch Drift (commit + file-content combined)

1. Add a new page: **Page → New Page**. Rename it `Branch Drift`.
2. Add two new data sources (one per query file), each via **Resource → Manage added data
   sources → Add a data source → BigQuery → Custom Query**:
   - Paste the full contents of `looker_sql/commit_drift_report.sql` (the first, non-commented
     query block only — stop before the `/* ... */` commented alternate queries at the bottom).
     Name it `Commit Drift`.
   - Paste the full contents of `looker_sql/file_drift_report.sql` (same — main query only).
     Name it `File Drift`.
3. **Heat-map — severity by repo × drift direction** (data source: `Commit Drift`)
   - Insert → Table with heatmap, or Insert → Pivot table with heatmap bars.
   - Rows: `repo`. Columns: `drift_direction`. Metric: `unique_commits`. Enable heatmap
     formatting on the metric, colour by `severity` if using a table instead of pivot.
4. **Bar chart — top drifted repos** (data source: `Commit Drift`)
   - Insert → Bar chart. Dimension: `repo`. Metric: `unique_commits`. Sort descending, limit to
     top 10–15 rows.
5. **Stacked bar — file change-type breakdown** (data source: `File Drift`)
   - Insert → Bar chart (stacked). Dimension: `repo`. Metrics: `files_added`, `files_modified`,
     `files_deleted`, `files_other`.
6. **Table — author leaderboard** (data source: `Commit Drift`)
   - Insert → Table. Dimension: `repo`. Metric: `distinct_authors`, sorted descending.
7. **Timeline — drift volume over time** (data source: `Commit Drift`, duplicate for `File
   Drift` as a second chart if you want both on screen)
   - Insert → Time series. Dimension: `execution_ts`. Metric: `unique_commits` (or
     `unique_files` for the File Drift version).
8. Add a **dropdown filter control** at the top of the page bound to `repo` (data source:
   `Commit Drift`) so viewers can isolate one repository across every chart on the page.

---

## Step 4 — Build Page 3: Environment vs Code Drift

1. Add a new page, rename it `Env Drift`.
2. Add a data source: Custom Query, paste the main query from `looker_sql/env_drift_report.sql`.
   Name it `Env Drift`.
3. **Stacked bar — drift by product/component**
   - Insert → Bar chart (stacked). Dimension: `product`. Breakdown dimension:
     `component_type`. Metric: `total_findings`.
4. **Donut — severity distribution**
   - Insert → Pie chart (donut). Dimension: `severity`. Metric: `total_findings`.
5. **Heat-map — component type × product**
   - Insert → Pivot table with heatmap. Rows: `component_type`. Columns: `product`. Metric:
     `total_findings`.
6. **Table — top unmanaged objects**
   - Insert → Table. Dimensions: `product`, `component_type`, `drift_category`, `severity`.
     Metrics: `in_env_not_in_code`, `in_code_not_in_env`, `content_mismatch`. Sort by `severity`
     then by the largest mismatch count.
7. **Timeline — finding count over time**
   - Insert → Time series. Dimension: `execution_ts`. Metric: `total_findings`.

---

## Step 5 — Build Page 4: Orphan BigQuery Datasets

1. Add a new page, rename it `Orphan Datasets`.
2. Add a data source: Custom Query, paste the main query from
   `looker_sql/orphan_datasets_report.sql`. Name it `Orphan Datasets`.
3. **Bar/pie — orphan count by status**
   - Insert → Pie chart or Bar chart. Dimension: `orphan_status`. Metric: record count (or
     `dataset_name` with "Count Distinct" aggregation).
4. **Scorecard — storage at risk**
   - Insert → Scorecard. Metric: `total_storage_mb`, aggregation SUM. Add a filter:
     `orphan_status` = the "confirmed orphan" value used by the report (check the actual values
     in `orphan_status` — they come from `unmatched_bq_datasets_report.py`).
5. **Table — top owners**
   - Insert → Table. Dimension: `owner`. Metric: `dataset_name` (Count Distinct). Sort
     descending.
6. **Histogram — risk score distribution**
   - Insert → Bar chart (or use a calculated field to bucket `risk_score` into ranges, e.g.
     0–25, 26–50, 51–75, 76–100, then chart count per bucket).
7. **Timeline — orphan count over time**
   - Insert → Time series. Dimension: `execution_ts`. Metric: `dataset_name` (Count Distinct).

---

## Step 6 — Add cross-cutting filter controls

These apply page-wide (or report-wide if you want them visible on every page):

1. Insert → Date range control. Default to "Last 30 days". Place it once per page (or once on a
   master page element if your Looker Studio layout supports it).
2. Insert → Filter control (dropdown), bound to `severity` where that field exists (Branch
   Drift, Env Drift pages) — lets viewers isolate high-severity findings only.
3. Optional: a filter control bound to `environment` if you run reports against multiple
   environments.

To make a control apply to multiple charts at once, select it, then in the right panel under
**Filter**, make sure "Apply to: All charts on this page" (or "All pages" if available in your
Looker Studio version) is selected.

---

## Step 7 — Share the dashboard

1. Verify all data sources use **Service Account Credentials** (Step 0.5) — viewers do not
   need their own GCP access once this is configured.
2. Click **Share** in the top right.
3. Add the `telefonica.de` Google Group or specific users who should view it. Looker Studio
   controls who can open the report; data access goes through the service account.
4. Optional: click **File → Schedule email delivery** to send a periodic snapshot (e.g. weekly)
   to stakeholders who don't need to log in directly.

---

## Additional chart: total discrepancies per repository for a selected time period

This chart lets a viewer pick a date range and immediately see how many drift findings
each repository produced — useful as a standalone scorecard tile or as an addition to
the Env Drift page (Step 4).

### Data source

**Resource → Manage added data sources → Add a data source → BigQuery → Custom Query**,
project `tefde-gcp-fastoss-dev`, paste the following query. Name it
`Env Drift Findings Over Time`.

```sql
SELECT
  DATE(e.execution_ts)  AS report_date,
  f.product             AS repo,
  f.component_type,
  f.drift_category,
  COUNT(*)              AS total_findings
FROM `tefde-gcp-fastoss-dev.devops_reports.env_drift_findings` f
JOIN `tefde-gcp-fastoss-dev.devops_reports.executions` e
  USING (execution_id)
WHERE e.status      = 'success'
  AND e.report_type = 'env_drift'
GROUP BY 1, 2, 3, 4
ORDER BY 1 DESC, 5 DESC
```

### Date range control

**Insert → Date range control**, bind it to `Env Drift Findings Over Time`, default to
**Last 30 days**. Every chart on the page that uses this data source will respond to it
automatically.

### Chart options

Choose the view that suits your audience:

**Option A — Bar chart: total findings per repo**
- Insert → Bar chart
- Dimension: `repo`
- Metric: `total_findings` (SUM), sorted descending
- → Shows which repos have the most drift in the chosen period

**Option B — Time series: trend over time**
- Insert → Time series
- Dimension: `report_date`
- Breakdown dimension: `repo` (optional — one line per repo)
- Metric: `total_findings` (SUM)
- → Shows whether drift is increasing or decreasing across the selected period

**Option C — Stacked bar: findings per repo broken down by drift category**
- Insert → Bar chart (stacked)
- Dimension: `repo`
- Breakdown dimension: `drift_category`
- Metric: `total_findings` (SUM)
- → Shows not just how many but *what type* of drift each repo has

**Option D — Grand total scorecard**
- Insert → Scorecard
- Same data source, Metric: `total_findings` (SUM), no dimension
- → Responds to the date range control and shows one number: total findings across
  all repos in the selected period

---

## Notes

- All Custom Query data sources re-run their SQL against BigQuery on every page load/filter
  change. If a page feels slow, consider materializing a query as a BigQuery view (like
  `execution_daily_summary` already is) and pointing the data source at the view's table name
  instead of a Custom Query.
- If you change a query in `looker_sql/`, the corresponding Looker Studio data source does
  **not** update automatically — open **Resource → Manage added data sources**, edit the data
  source, and re-paste the updated query.
- See `Instructions/Running the Reports.md` for how the underlying data gets into BigQuery in
  the first place (scheduled and manual report runs).

---

## Pre-built BigQuery views (no custom SQL needed)

Two additional views are already defined in `BQ DS + Tables.tf` and require no custom query — connect to them directly as table data sources.

### `env_drift_job_summary` — job-level run status

**Connect:** Add data → BigQuery → `tefde-gcp-fastoss-dev` → `devops_reports` → `env_drift_job_summary`

Returns one row per environment showing the **latest** Cloud Run job execution status and repo counts.

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `execution_ts` | Date dimension | Job start timestamp |
| `environment` | Dimension | `prod`, `test`, or `dev` |
| `status` | Dimension | `success` / `success_with_warnings` / `failed` |
| `repos_total` | Metric | Directories found in subgroup after cloning |
| `repos_launched` | Metric | Repos actually processed (had `.git`, not excluded) |
| `repos_success` | Metric | Repos that completed without error |
| `repos_failed` | Metric | Repos that exited with a non-zero code |
| `repos_skipped` | Metric | `repos_total − repos_launched` (clone failures + excluded repos) |
| `duration_seconds` | Metric | Total job elapsed time in seconds |

**Status meanings:** `success` = all repos processed OK; `success_with_warnings` = some repos were skipped (clone failure or `EXCLUDE_REPOS` match); `failed` = one or more repos exited non-zero.

For a full step-by-step setup guide including conditional formatting and historical backfill SQL, see `Instructions/Building the Job Run Status Dashboard.md`.

---

### `env_drift_summary` — per-repository env-drift dashboard

**Connect:** Add data → BigQuery → `tefde-gcp-fastoss-dev` → `devops_reports` → `env_drift_summary`

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `repository` | Dimension | GitLab project name |
| `execution_date` | Dimension / Date | Use as the date range field |
| `run_number` | Dimension | Sequential run number per repo per day (1 = first run) |
| `bq_findings` | Metric | Count of BigQuery drift findings |
| `gcs_findings` | Metric | Count of GCS drift findings |
| `report_url` | URL | Authenticated GCS link to the `report.md` file — set field type to **URL** in the data source settings |

**Suggested chart layout:**
1. **Table** — Dimensions: `repository`, `run_number`, `report_url`; Metrics: `bq_findings`, `gcs_findings`
2. **Filter controls** — Date range (field: `execution_date`), Dropdown (field: `repository`), Dropdown (field: `run_number`)

Set the `report_url` field type to **URL** in the data source settings so it renders as a clickable link in the table. Then in the table's Style tab, find the `report_url` column and enable **Hyperlink**.

> **Important:** `report_url` must be placed in **Dimensions**, not Metrics. If placed in the Metric bucket, Looker Studio treats it as a number (Count Distinct) and the URL type is lost.

---

### `management_dashboard` — executive red/green health grid

**Connect:** Add data → BigQuery → `tefde-gcp-fastoss-dev` → `devops_reports` → `management_dashboard`

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `repository` | Dimension | GitLab project name |
| `run_date` | Dimension / Date | Use as the date range field |
| `run_number` | Dimension | Sequential env-drift run number per day |
| `bq_findings` | Metric | BigQuery drift findings count |
| `gcs_findings` | Metric | GCS drift findings count |
| `branch_drift` | Metric | Total unique commits across all branch comparisons (commit drift) |
| `file_drift` | Metric | Total unique files across all branch comparisons (file drift) |
| `status` | Dimension | `All clear` (all four metrics = 0) or `Has findings` |

**Suggested chart layout:**

1. **Calculated fields** — for each of the four metrics, create a calculated field that shows a dot for zero and the number for non-zero:
   ```
   IF(bq_findings = 0, "●", TEXT(bq_findings))
   ```
   Name these `GCP`, `GCS`, `Branch drift`, `File drift`.

2. **Table** — Dimension: `repository`; Metrics: the four calculated fields. In the **Style** tab, add conditional formatting per column:
   - Text **contains** `●` → font color `#1B8A00` (green)
   - Text **does not contain** `●` → font color `#C62828` (red), bold

3. **Filter controls:**

   | Control | Type | Field | Purpose |
   |---|---|---|---|
   | Date | Date range picker | `run_date` | Select report date |
   | Run | Dropdown | `run_number` | Select which run of the day |
   | Status | Dropdown | `status` | Toggle between **All**, **Has findings**, **All clear** |

4. **Optional scorecards** — four Scorecard charts at the top (one per metric, SUM aggregation) give a single-number summary for the selected filters.
