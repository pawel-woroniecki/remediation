# Building the Dev Env Drift Dashboard in Looker Studio

This document explains how to build the Dev Environment Drift Looker Studio dashboard —
a per-repository breakdown of discrepancies between the **master branch** in GitLab and
what is actually deployed in **tefde-gcp-fastoss-dev-gke** (BigQuery and GCS).

---

## What the dashboard shows

| Column | Description |
|---|---|
| `product` | GitLab project name |
| `component_type` | `bigquery` or `gcs` |
| `drift_category` | e.g. `only_in_env`, `only_in_source`, `definition_mismatch`, `schema_mismatch` |
| `severity` | `high` / `medium` / `low` / `none` |
| `git_ref` | Branch compared (`master`) |
| `environment` | Always `dev` |
| `total_findings` | Total number of drifted objects |
| `distinct_objects` | Distinct object names affected |
| `in_env_not_in_code` | Objects deployed but missing from source |
| `in_code_not_in_env` | Objects in code but not yet deployed |
| `content_mismatch` | Objects present in both but with differing definition/schema |

---

## Prerequisites

- At least one `devops-reports-env-drift-dev` Cloud Run Job execution has completed
  successfully (so the `env_drift_findings` table has data for `environment = 'dev'`).
- A `telefonica.de` Google account with read access to `tefde-gcp-fastoss-dev`.
- The SQL file `TEF remediation/looker_sql/env_drift_dev_report.sql` is available to copy from.

---

## Step 1 — Create the report and connect the data source

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com) and sign in.
2. Click **Create → Report**.
3. In the data source picker choose **BigQuery → Custom Query**.
4. Set the billing project to `tefde-gcp-fastoss-dev`.
5. Paste the **main query** from `TEF remediation/looker_sql/env_drift_dev_report.sql`
   into the query box. Use only the first query block — stop before the first
   `/* ---- */` comment separator.
6. Name the data source `Env Drift — Dev`.
7. Click **Add** (top right) → **Add to Report**.

> **Which query to paste:** The file contains three blocks. The active one starts with
> `WITH latest_findings AS (` and ends with `ORDER BY severity_sort, total_findings DESC, ...`.
> The two commented-out blocks below are for optional historical and drill-through tiles —
> do not include them.

---

## Step 2 — Set field types

1. Click **Resource → Manage added data sources → pencil icon** on `Env Drift — Dev`.
2. Set the following:

   | Field | Change to |
   |---|---|
   | `execution_ts` | **Date & Time** — set as **Date range dimension** |
   | `total_findings` | **Number**, Aggregation: **Sum** |
   | `distinct_objects` | **Number**, Aggregation: **Sum** |
   | `in_env_not_in_code` | **Number**, Aggregation: **Sum** |
   | `in_code_not_in_env` | **Number**, Aggregation: **Sum** |
   | `content_mismatch` | **Number**, Aggregation: **Sum** |

3. The remaining fields (`product`, `component_type`, `drift_category`, `severity`,
   `git_ref`, `environment`, `triggered_by`) should already be **Text** dimensions —
   confirm and leave unchanged.

4. Click **Done → Close**.

---

## Step 3 — Build the main table

1. **Insert → Table**.
2. In the **Setup** panel, set:
   - **Dimensions:** `product`, `component_type`, `drift_category`, `severity`
   - **Metrics:** `total_findings`, `in_env_not_in_code`, `in_code_not_in_env`,
     `content_mismatch`
   - **Sort:** `total_findings` descending (most-drifted repos appear first).
   - **Rows per page:** `50`.
3. **Date range dimension:** scroll down in Setup and set it to `execution_ts`.

---

## Step 4 — Add a bar chart: drift by product

1. **Insert → Bar chart**.
2. Setup:
   - **Dimension:** `product`
   - **Breakdowns:** `drift_category`
   - **Metric:** `total_findings` (SUM)
   - **Sort:** `total_findings` descending
   - **Number of rows:** `15`
   - Enable **Stacked bars** in the Style tab.
3. This shows which repos have the most drift and which categories dominate.

---

## Step 5 — Add filter controls

Insert these four controls above the table and bar chart:

### Filter 1 — Date range

1. **Insert → Date range control**.
2. Set **Default date range** to **Yesterday** (shows the most recent run by default).
3. Bind to field `execution_ts`.

### Filter 2 — Product (repository)

1. **Insert → Filter control**.
2. Field: `product`. Control type: **Drop-down list**. Label: `Repository`.

### Filter 3 — Severity

1. **Insert → Filter control**.
2. Field: `severity`. Control type: **Drop-down list**. Label: `Severity`.
3. Use this to show only `high` or `medium` severity rows.

### Filter 4 — Component type

1. **Insert → Filter control**.
2. Field: `component_type`. Control type: **Drop-down list**. Label: `Component`.
3. Use this to switch between BigQuery and GCS findings.

> To make all four controls apply to every chart: select each control → right panel →
> **Filter** section → confirm **All charts on this page** is selected.

---

## Step 6 — Optional: add summary scorecards

Four scorecard tiles at the top give totals for the selected filters.

1. **Insert → Scorecard**. Metric: `total_findings` (SUM). Label: `Total findings`.
2. **Insert → Scorecard**. Metric: `in_env_not_in_code` (SUM). Label: `Only in env`.
3. **Insert → Scorecard**. Metric: `in_code_not_in_env` (SUM). Label: `Only in code`.
4. **Insert → Scorecard**. Metric: `content_mismatch` (SUM). Label: `Content mismatch`.
5. Arrange them in a row above the controls.

---

## Step 7 — Share

1. Click **Share** (top right).
2. Add the team or Google Group.

For organisation-wide access where viewers do not need their own GCP permissions, follow the
**Step 0 — One-time GCP setup for Service Account Credentials** instructions in
`Instructions/Building the Looker Studio Dashboards.md`.

---

## What the finished dashboard looks like

| product | component_type | drift_category | severity | findings | in env | in code | mismatch |
|---|---|---|---|---|---|---|---|
| operations_mobile | bigquery | schema_mismatch | high | 8 | 0 | 0 | 8 |
| geo | bigquery | only_in_source | medium | 3 | 0 | 3 | 0 |
| perf_mgmt_ip | gcs | only_in_env | low | 1 | 1 | 0 | 0 |

---

## Key difference from the prod and test env drift dashboards

| Aspect | Prod | Test | Dev |
|---|---|---|---|
| Branch compared | `production` | `test` | `master` |
| BQ project scanned | `tefde-gcp-fastoss-prod` | `tefde-gcp-fastoss-test` | `tefde-gcp-fastoss-dev-gke` |
| Cloud Run Job | `devops-reports-env-drift` | `devops-reports-env-drift-test` | `devops-reports-env-drift-dev` |
| Schedule | 05:10 Berlin | 05:40 Berlin | 05:50 Berlin |
| Environment filter in SQL | `AND e.environment = 'prod'` | `AND e.environment = 'test'` | `AND e.environment = 'dev'` |
| SQL file | `looker_sql/env_drift_report.sql` | `looker_sql/env_drift_test_report.sql` | `looker_sql/env_drift_dev_report.sql` |

---

## Related

- `Instructions/Building the Test Env Drift Dashboard.md` — same structure for test branch
- `Instructions/Building the Env Drift Summary Dashboard.md` — prod environment summary
- `Instructions/Building the Management Dashboard.md` — executive red/green grid (prod only)
- `TEF remediation/looker_sql/env_drift_dev_report.sql` — the SQL query used as data source
- `TEF remediation/Terraform/Cloud Run Jobs.tf` — `env_drift_dev` job definition
