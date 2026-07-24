# Building the File Drift Dashboard in Looker Studio

This document explains how to build the File Drift Looker Studio dashboard — a per-repository
table showing which files differ between branches (by change type: added, modified, deleted),
for the most recent successful run.

---

## What the dashboard shows

| Column | Description |
|---|---|
| `repo` | GitLab project name |
| `drift_direction` | e.g. `main differs from develop` — files that differ between the two branches |
| `severity` | `high` / `medium` / `low` / `none` — computed by the report script |
| `left_branch` | The "base" branch |
| `right_branch` | The "comparison" branch |
| `unique_files` | Total number of files that differ between the branches |
| `files_added` | Files present in right_branch but absent from left_branch |
| `files_modified` | Files present in both branches but with different content |
| `files_deleted` | Files present in left_branch but removed in right_branch |
| `files_other` | Files with an unclassified change type |
| `distinct_authors` | Number of distinct authors of the differing file changes |

The stacked bar chart shows the breakdown of added / modified / deleted per repository at a
glance — a useful companion to the raw counts in the table.

---

## Prerequisites

- At least one `devops-reports-file-drift` Cloud Run Job execution has completed successfully
  (so the `branch_drift_kpis` and `branch_drift_evidence` tables have data).
- A `telefonica.de` Google account with read access to `tefde-gcp-fastoss-dev`.
- The SQL file `TEF remediation/looker_sql/file_drift_report.sql` is available to copy from.

---

## Step 1 — Create the report and connect the data source

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com) and sign in.
2. Click **Create → Report**.
3. In the data source picker choose **BigQuery → Custom Query**.
4. Set the billing project to `tefde-gcp-fastoss-dev`.
5. Paste the **main query** from `TEF remediation/looker_sql/file_drift_report.sql` into
   the query box. Use only the first query block — stop before the `/* ---- */` comment
   separator that precedes the commented-out drill-through query.
6. Name the data source `File Drift`.
7. Click **Add** (top right) → **Add to Report**.

> **Which query to paste:** The file contains two query blocks. The active one starts with
> `WITH latest_exec AS (` and ends with `ORDER BY ks.severity_sort, ks.unique_files DESC, ...`.
> Everything after the first `/* ---- */` divider is the file-level evidence query —
> do not include it.

---

## Step 2 — Set field types

1. Click **Resource → Manage added data sources → pencil icon** on `File Drift`.
2. Set the following:

   | Field | Change to |
   |---|---|
   | `execution_ts` | **Date & Time** — set as **Date range dimension** |
   | `unique_files` | **Number**, Aggregation: **Sum** |
   | `unique_commits` | **Number**, Aggregation: **Sum** |
   | `files_added` | **Number**, Aggregation: **Sum** |
   | `files_modified` | **Number**, Aggregation: **Sum** |
   | `files_deleted` | **Number**, Aggregation: **Sum** |
   | `files_other` | **Number**, Aggregation: **Sum** |
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
   - **Metrics:** `unique_files`, `files_added`, `files_modified`, `files_deleted`,
     `files_other`
   - **Sort:** `unique_files` descending (repos with the most differing files appear first).
   - **Rows per page:** `50`.
3. **Date range dimension:** scroll down in Setup and set it to `execution_ts`.

---

## Step 4 — Add a stacked bar chart: file change breakdown per repo

1. **Insert → Bar chart**.
2. In the **Setup** panel:
   - **Dimension:** `repo`
   - **Metrics:** `files_added`, `files_modified`, `files_deleted`, `files_other`
   - Enable **Stacked bars** in the Style tab.
   - **Sort:** `unique_files` descending (or sort by the tallest bar — `files_modified`).
   - **Number of rows:** `15`
3. In the **Style** tab, assign distinct colours:
   - `files_added` → green (e.g. `#1B8A00`)
   - `files_modified` → orange (e.g. `#E65100`)
   - `files_deleted` → red (e.g. `#C62828`)
   - `files_other` → grey (e.g. `#757575`)

This chart makes it immediately clear whether drift is mostly new files, edits to existing
files, or deletions — which helps distinguish an active feature branch (many adds) from
a diverged maintenance branch (many modifies).

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
3. Use this to show only `high` or `medium` severity rows.

### Filter 4 — Drift direction

1. **Insert → Filter control**.
2. Field: `drift_direction`. Control type: **Drop-down list**. Label: `Direction`.
3. Useful when a repo is compared in both directions and you want to focus on one.

> To make all four controls apply to every chart: select each control → right panel →
> **Filter** section → confirm **All charts on this page** is selected.

---

## Step 6 — Optional: add summary scorecards

Four scorecard tiles at the top give a single-number total for the selected filters.

1. **Insert → Scorecard**. Metric: `unique_files` (SUM). Label: `Drifted files`.
2. **Insert → Scorecard**. Metric: `files_added` (SUM). Label: `Added`.
3. **Insert → Scorecard**. Metric: `files_modified` (SUM). Label: `Modified`.
4. **Insert → Scorecard**. Metric: `files_deleted` (SUM). Label: `Deleted`.
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

| repo | drift_direction | severity | files | added | modified | deleted |
|---|---|---|---|---|---|---|
| operations_mobile | main differs from develop | high | 23 | 5 | 17 | 1 |
| perf_mgmt_ip | develop differs from main | low | 2 | 0 | 2 | 0 |
| ndl_core_base | main differs from develop | none | 0 | 0 | 0 | 0 |

The stacked bar chart above the table shows that `operations_mobile` has mostly modified files
(orange) with a few additions (green), while `perf_mgmt_ip` has only modifications. Applying
`Severity = high` hides clean repos.

---

## Data source field reference

| Field | Type | Description |
|---|---|---|
| `execution_ts` | Date dimension | Run start timestamp — use as date range filter field |
| `environment` | Dimension | GCP environment label |
| `triggered_by` | Dimension | Email or identity that triggered the run |
| `repo` | Dimension | GitLab project name |
| `drift_direction` | Dimension | Human-readable label: `<right_branch> differs from <left_branch>` |
| `left_branch` | Dimension | The base branch (reference point) |
| `right_branch` | Dimension | The comparison branch |
| `comparison_mode` | Dimension | How the comparison was performed |
| `branch_status` | Dimension | `ok` / `error` — whether the comparison ran cleanly |
| `severity` | Dimension | `high` / `medium` / `low` / `none` |
| `unique_commits` | Metric | Commits associated with the differing files |
| `unique_files` | Metric | Files that differ between the two branches (primary metric) |
| `distinct_authors` | Metric | Number of distinct authors of the differing file changes |
| `files_added` | Metric | Files present in right_branch but not in left_branch |
| `files_modified` | Metric | Files present in both branches but with different content |
| `files_deleted` | Metric | Files removed in right_branch relative to left_branch |
| `files_other` | Metric | Files with an unclassified change type |
| `earliest_change_date` | Timestamp | Date of the oldest differing file's last commit |
| `latest_change_date` | Timestamp | Date of the most recent differing file's last commit |

---

## Difference from Commit Drift

| Aspect | Commit Drift | File Drift |
|---|---|---|
| Primary metric | `unique_commits` | `unique_files` |
| What is counted | Commits in right_branch absent from left_branch | Files whose content differs between branches |
| Evidence breakdown | Author count, date range | Added / modified / deleted / other counts |
| Drift direction label | `X not in Y` | `X differs from Y` |
| BQ filter | `drift_type = 'commit'` | `drift_type = 'content'` |

Use **Commit Drift** to understand how far two branches have diverged in terms of development
activity. Use **File Drift** to see exactly which files are out of sync and in which direction
the change went.

---

## Related

- `Instructions/Building the Commit Drift Dashboard.md` — commit-based branch drift
- `Instructions/Building the Env Drift Summary Dashboard.md` — BigQuery/GCS schema drift
- `Instructions/Building the Looker Studio Dashboards.md` — full 4-page dashboard guide and
  one-time GCP service account setup
- `Instructions/Building the Management Dashboard.md` — executive red/green health grid
- `TEF remediation/looker_sql/file_drift_report.sql` — the SQL query used as data source
- `TEF remediation/Terraform/BQ DS + Tables.tf` — `branch_drift_kpis` and
  `branch_drift_evidence` table schema definitions
