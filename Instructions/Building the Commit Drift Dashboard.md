# Building the Commit Drift Dashboard in Looker Studio

This document explains how to build the Commit Drift Looker Studio dashboard — a per-repository
table showing how many commits exist in one branch but not another, along with the authors and
dates of those commits, for the most recent successful run.

---

## What the dashboard shows

| Column | Description |
|---|---|
| `repo` | GitLab project name |
| `drift_direction` | e.g. `main not in develop` — commits present in right_branch but absent from left_branch |
| `severity` | `high` / `medium` / `low` / `none` — computed by the report script |
| `left_branch` | The "base" branch (commits expected here) |
| `right_branch` | The "comparison" branch (commits found here but not in left) |
| `unique_commits` | Number of commits in the drift set |
| `unique_files` | Distinct files touched by those commits |
| `distinct_authors` | Number of distinct commit authors |
| `earliest_commit_date` | Date of the oldest drifted commit |
| `latest_commit_date` | Date of the most recent drifted commit |

---

## Prerequisites

- At least one `devops-reports-commit-drift` Cloud Run Job execution has completed
  successfully (so the `branch_drift_kpis` and `branch_drift_evidence` tables have data).
- A `telefonica.de` Google account with read access to `tefde-gcp-fastoss-dev`.
- The SQL file `TEF remediation/looker_sql/commit_drift_report.sql` is available to copy from.

---

## Step 1 — Create the report and connect the data source

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com) and sign in.
2. Click **Create → Report**.
3. In the data source picker choose **BigQuery → Custom Query**.
4. Set the billing project to `tefde-gcp-fastoss-dev`.
5. Paste the **main query** from `TEF remediation/looker_sql/commit_drift_report.sql` into
   the query box. Use only the first query block — stop before the `/* ---- */` comment
   separator that precedes the commented-out drill-through query.
6. Name the data source `Commit Drift`.
7. Click **Add** (top right) → **Add to Report**.

> **Which query to paste:** The file contains two query blocks. The active one starts with
> `WITH latest_exec AS (` and ends with `ORDER BY ks.severity_sort, ks.unique_commits DESC, ...`.
> Everything after the first `/* ---- */` divider is the commented-out drill-through query —
> do not include it.

---

## Step 2 — Set field types

1. Click **Resource → Manage added data sources → pencil icon** on `Commit Drift`.
2. Set the following:

   | Field | Change to |
   |---|---|
   | `execution_ts` | **Date & Time** — set as **Date range dimension** |
   | `unique_commits` | **Number**, Aggregation: **Sum** |
   | `unique_files` | **Number**, Aggregation: **Sum** |
   | `distinct_authors` | **Number**, Aggregation: **Sum** |

3. The remaining fields (`repo`, `drift_direction`, `severity`, `left_branch`,
   `right_branch`, `comparison_mode`, `branch_status`, `triggered_by`, `environment`)
   should already be **Text** dimensions — confirm and leave unchanged.

4. Click **Done → Close**.

---

## Step 3 — Build the main table

1. **Insert → Table**.
2. In the **Setup** panel, set:
   - **Dimensions:** `repo`, `drift_direction`, `severity`, `left_branch`, `right_branch`
   - **Metrics:** `unique_commits`, `unique_files`, `distinct_authors`
   - **Sort:** `unique_commits` descending (most-drifted repos appear first).
   - **Rows per page:** `50`.
3. **Date range dimension:** scroll down in Setup and set it to `execution_ts`.

> `repo` and `drift_direction` together identify one row. A repository with three branch pairs
> being compared will appear as three rows, one per pair.

---

## Step 4 — Add a bar chart: top repos by commit drift

1. **Insert → Bar chart**.
2. Setup:
   - **Dimension:** `repo`
   - **Metric:** `unique_commits` (SUM)
   - **Sort:** `unique_commits` descending
   - **Number of rows:** `15`
3. This gives a quick view of which repos have the most out-of-sync commits.

---

## Step 5 — Add filter controls

Insert these four controls above the table and bar chart:

### Filter 1 — Date range

1. **Insert → Date range control**.
2. Set **Default date range** to **Yesterday** (shows the most recent run by default).
3. Bind to field `execution_ts`.

### Filter 2 — Repository

1. **Insert → Filter control**.
2. Field: `repo`. Control type: **Drop-down list**. Label: `Repository`.

### Filter 3 — Severity

1. **Insert → Filter control**.
2. Field: `severity`. Control type: **Drop-down list**. Label: `Severity`.
3. Use this to show only `high` or `medium` severity rows and ignore clean ones.

### Filter 4 — Drift direction

1. **Insert → Filter control**.
2. Field: `drift_direction`. Control type: **Drop-down list**. Label: `Direction`.
3. Useful when a repo is compared in both directions (e.g. main→develop and develop→main)
   and you want to focus on one.

> To make all four controls apply to every chart: select each control → right panel →
> **Filter** section → confirm **All charts on this page** is selected.

---

## Step 6 — Optional: add summary scorecards

Three scorecard tiles at the top give a single-number total for the selected filters.

1. **Insert → Scorecard**. Metric: `unique_commits` (SUM). Label: `Drifted commits`.
2. **Insert → Scorecard**. Metric: `unique_files` (SUM). Label: `Files affected`.
3. **Insert → Scorecard**. Metric: `distinct_authors` (SUM). Label: `Authors`.
4. Arrange them in a row above the controls.

---

## Step 7 — Share

1. Click **Share** (top right).
2. Add the team or Google Group.

For organisation-wide access where viewers do not need their own GCP permissions, follow the
**Step 0 — One-time GCP setup for Service Account Credentials** instructions in
`Instructions/Building the Looker Studio Dashboards.md`.

---

## What the finished dashboard looks like

| repo | drift_direction | severity | commits | files | authors |
|---|---|---|---|---|---|
| operations_mobile | main not in develop | high | 12 | 45 | 3 |
| perf_mgmt_ip | develop not in main | medium | 4 | 8 | 1 |
| ndl_core_base | main not in develop | none | 0 | 0 | 0 |

The table is sorted by `unique_commits` descending so the most out-of-sync repositories
appear first. Applying `Severity = high` hides clean repos and shows only the ones that
need attention. The bar chart on the right mirrors the sort order visually.

---

## Data source field reference

| Field | Type | Description |
|---|---|---|
| `execution_ts` | Date dimension | Run start timestamp — use as date range filter field |
| `environment` | Dimension | GCP environment label |
| `triggered_by` | Dimension | Email or identity that triggered the run |
| `repo` | Dimension | GitLab project name |
| `drift_direction` | Dimension | Human-readable label: `<right_branch> not in <left_branch>` |
| `left_branch` | Dimension | The base branch (reference point) |
| `right_branch` | Dimension | The comparison branch (source of unique commits) |
| `comparison_mode` | Dimension | How the comparison was performed |
| `branch_status` | Dimension | `ok` / `error` — whether the comparison ran cleanly |
| `severity` | Dimension | `high` / `medium` / `low` / `none` |
| `unique_commits` | Metric | Commits present in right_branch but not left_branch |
| `unique_files` | Metric | Distinct files touched by those commits |
| `distinct_authors` | Metric | Number of distinct commit authors in the drift set |
| `earliest_commit_date` | Timestamp | Date of the oldest drifted commit |
| `latest_commit_date` | Timestamp | Date of the most recent drifted commit |

---

## Related

- `Instructions/Building the File Drift Dashboard.md` — file-content branch drift (which files
  differ, by change type: added / modified / deleted)
- `Instructions/Building the Env Drift Summary Dashboard.md` — BigQuery/GCS schema drift
- `Instructions/Building the Looker Studio Dashboards.md` — full 4-page dashboard guide and
  one-time GCP service account setup
- `Instructions/Building the Management Dashboard.md` — executive red/green health grid
- `TEF remediation/looker_sql/commit_drift_report.sql` — the SQL query used as data source
- `TEF remediation/Terraform/BQ DS + Tables.tf` — `branch_drift_kpis` and
  `branch_drift_evidence` table schema definitions
