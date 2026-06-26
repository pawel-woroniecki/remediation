# Building the Looker Studio Dashboards — Step-by-Step Guide

This document walks through building a 4-page Looker Studio report on top of the
`devops_reports` BigQuery dataset: an Overview/Health page plus one page per report type. It
uses the queries already written in `looker_sql/` and the `execution_daily_summary` view.

No service account or key is needed — Looker Studio connects using your own Google identity.

---

## Prerequisites

- A `telefonica.de` Google account with BigQuery read access to `tefde-gcp-fastoss-dev`
  (`devops_reports` dataset).
- The files in `looker_sql/`: `commit_drift_report.sql`, `file_drift_report.sql`,
  `env_drift_report.sql`, `orphan_datasets_report.sql`. Each already has the GCP project ID
  filled in (`tefde-gcp-fastoss-dev`).

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

1. Click **Share** in the top right.
2. Add the `telefonica.de` Google Group or specific users who should view it — access is
   controlled entirely within Looker Studio, not GCP IAM.
3. Optional: click **File → Schedule email delivery** to send a periodic snapshot (e.g. weekly)
   to stakeholders who don't need to log in directly.

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
