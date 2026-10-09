# Building the File Drift Dashboard in Looker Studio

This document explains how to build the File Drift Looker Studio dashboard — a per-repository
table showing how many files differ in content between branches (added, modified, deleted),
for the run date selected by the user.

---

## What the dashboard shows

| Column | Description |
|---|---|
| `repo` | GitLab project name |
| `drift_direction` | e.g. `main differs from develop` — branches being compared |
| `severity` | `high` / `medium` / `low` / `none` — computed by the report script |
| `left_branch` | The "base" branch |
| `right_branch` | The "comparison" branch |
| `unique_files` | Total number of files that differ between the branches |
| `files_added` | Files present in right_branch but not in left_branch |
| `files_modified` | Files present in both but with different content |
| `files_deleted` | Files present in left_branch but not in right_branch |
| `files_other` | Files with an unrecognised change type |
| `distinct_authors` | Number of distinct last-commit authors across differing files |
| `earliest_change_date` | Date of the oldest last-commit among differing files |
| `latest_change_date` | Date of the most recent last-commit among differing files |

---

## Prerequisites

- At least one `devops-reports-file-drift` Cloud Run Job execution has completed
  successfully (so the `branch_drift_kpis` and `branch_drift_evidence` tables have data).
- `terraform apply` has been run and the `file_drift_report` view exists in `devops_reports`
  (verify: `SELECT * FROM tefde-gcp-fastoss-dev.devops_reports.file_drift_report LIMIT 1`).
- A `telefonica.de` Google account with read access to `tefde-gcp-fastoss-dev`.

---

## Step 1 — Create the report and connect the data source

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com) and sign in.
2. Click **Create → Report**.
3. In the data source picker choose **BigQuery → My Projects**.
4. Select **`tefde-gcp-fastoss-dev` → `devops_reports` → `file_drift_report`**.
5. Leave all options at their defaults and click **Connect**.
6. Name the data source `File Drift`.
7. Click **Add** (top right) → **Add to Report**.

> The `file_drift_report` view is defined in `TEF remediation/Terraform/BQ DS + Tables.tf`
> and includes a `run_number` field (1 = latest run for that date, 2 = previous run, …).
> The SQL file `TEF remediation/looker_sql/file_drift_report.sql` is kept as reference only —
> it does not include `run_number` and is no longer the primary data source.

---

## Step 2 — Set field types

1. Click **Resource → Manage added data sources → pencil icon** on `File Drift`.
2. Set the following:

   | Field | Change to |
   |---|---|
   | `run_date` | **Date** (day-level) — used by the Run date dropdown filter |
   | `run_number` | **Number**, Aggregation: **None** — used by the Run number dropdown filter |
   | `execution_ts` | **Date & Time** |
   | `unique_files` | **Number**, Aggregation: **Sum** |
   | `files_added` | **Number**, Aggregation: **Sum** |
   | `files_modified` | **Number**, Aggregation: **Sum** |
   | `files_deleted` | **Number**, Aggregation: **Sum** |
   | `files_other` | **Number**, Aggregation: **Sum** |
   | `distinct_authors` | **Number**, Aggregation: **Sum** |
   | `unique_commits` | **Number**, Aggregation: **Sum** |

3. The remaining fields (`repo`, `drift_direction`, `severity`, `left_branch`,
   `right_branch`, `comparison_mode`, `branch_status`, `triggered_by`, `environment`)
   should already be **Text** dimensions — confirm and leave unchanged.

4. Click **Done → Close**.

---

## Step 3 — Build the main table

1. **Insert → Table**.
2. In the **Setup** panel, set:
   - **Dimensions:** `repo`, `drift_direction`, `severity`, `left_branch`, `right_branch`
   - **Metrics:** `unique_files`, `files_added`, `files_modified`, `files_deleted`
   - **Sort:** `unique_files` descending (most-drifted repos appear first).
   - **Rows per page:** `50`.
   - **Date range dimension:** `run_date` — this connects the chart to the Date Range Control.

> `repo` and `drift_direction` together identify one row. A repository compared across
> multiple branch pairs will appear as one row per pair.

---

## Step 4 — Add a bar chart: top repos by file drift

1. **Insert → Bar chart** (stacked).
2. Setup:
   - **Dimension:** `repo`
   - **Metrics:** `files_added`, `files_modified`, `files_deleted`, `files_other`
   - **Sort:** `unique_files` descending
   - **Number of rows:** `15`
3. This gives a visual breakdown of change types per repo — how many files are added vs
   modified vs deleted.

---

## Step 5 — Add filter controls

Insert these controls above the table and bar chart:

### Filter 0 — Date range

1. **Insert → Date range control**.
2. Set a default such as **Last 30 days**.
3. This control works via the **Date range dimension** set on each chart (`run_date`).
   Looker Studio automatically filters the query to the chosen period — no special
   data source setting is needed.

### Filter 1 — Run date

1. **Insert → Filter control**.
2. Field: `run_date`. Control type: **Drop-down list**. Label: `Run date`.
3. The dropdown lists every date within the Date Range Control window on which a
   successful run was recorded. Selecting one date shows the snapshot from that run.
4. Leaving the filter empty shows all runs within the selected period combined.

### Filter 2 — Run number

1. **Insert → Filter control**.
2. Field: `run_number`. Control type: **Drop-down list**. Label: `Run (1 = latest)`.
3. When the job runs more than once in a day (e.g. a scheduled run at 05:30 and a manual
   re-run after a bug fix), `run_number = 1` is the most recent run for the selected date
   and `run_number = 2` is the previous one.
4. Use together with the `run_date` filter to compare pre-fix and post-fix runs on the same
   day. Leaving this filter empty shows all runs for the selected date combined.

### Filter 3 — Repository

1. **Insert → Filter control**.
2. Field: `repo`. Control type: **Drop-down list**. Label: `Repository`.

### Filter 4 — Severity

1. **Insert → Filter control**.
2. Field: `severity`. Control type: **Drop-down list**. Label: `Severity`.
3. Use this to show only `high` or `medium` severity rows.

### Filter 5 — Drift direction

1. **Insert → Filter control**.
2. Field: `drift_direction`. Control type: **Drop-down list**. Label: `Direction`.

> To make all five controls apply to every chart: select each control → right panel →
> **Filter** section → confirm **All charts on this page** is selected.

---

## Step 6 — Add summary scorecards

Four scorecard tiles at the top give a single-number total for the selected filters.

1. **Insert → Scorecard**. Metric: `unique_files` (SUM). Label: `Files differing`.
2. **Insert → Scorecard**. Metric: `files_added` (SUM). Label: `Files added`.
3. **Insert → Scorecard**. Metric: `files_modified` (SUM). Label: `Files modified`.
4. **Insert → Scorecard**. Metric: `files_deleted` (SUM). Label: `Files deleted`.

---

## Step 7 — Conditional formatting on severity

1. Select the main table → **Style** tab → **Conditional formatting**.
2. Add rules on the `severity` dimension:

| Condition | Format |
|---|---|
| Text **is** `high` | Background `#FDECEA` (light red), text `#C62828` (dark red), **Bold** |
| Text **is** `medium` | Background `#FFF8E1` (light amber), text `#E65100` (orange) |
| Text **is** `low` | Background `#E3F2FD` (light blue), text `#1565C0` (dark blue) |

---

## Step 8 — Share

1. Click **Share** (top right).
2. Add the team or Google Group.

For organisation-wide access where viewers do not need their own GCP permissions, follow the
**Step 0 — One-time GCP setup for Service Account Credentials** instructions in
`Instructions/Building the Looker Studio Dashboards.md`.

---

## What the finished dashboard looks like

| repo | drift_direction | severity | files | added | modified | deleted |
|---|---|---|---|---|---|---|
| stage | main differs from develop | high | 391 | 391 | 0 | 0 |
| site | main differs from develop | medium | 42 | 18 | 20 | 4 |
| perf_mgmt_ran | main differs from develop | low | 8 | 3 | 5 | 0 |

---

## Data source field reference

### `File Drift` data source

| Field | Type | Description |
|---|---|---|
| `run_date` | Date | Calendar date of the run (Europe/Berlin) — use as the Run date dropdown filter field |
| `run_number` | Number | 1 = latest run for that date, 2 = previous run — use as the Run number dropdown filter field |
| `execution_ts` | Date & Time | Full run start timestamp |
| `environment` | Dimension | GCP environment label |
| `triggered_by` | Dimension | Email or identity that triggered the run |
| `repo` | Dimension | GitLab project name |
| `drift_direction` | Dimension | Human-readable label: `<right_branch> differs from <left_branch>` |
| `left_branch` | Dimension | The base branch (reference point) |
| `right_branch` | Dimension | The comparison branch |
| `comparison_mode` | Dimension | How the comparison was performed |
| `branch_status` | Dimension | `ok` / `error` — whether the comparison ran cleanly |
| `severity` | Dimension | `high` / `medium` / `low` / `none` |
| `unique_files` | Metric | Total files differing between the two branches |
| `unique_commits` | Metric | Commits associated with the differing files |
| `files_added` | Metric | Files present in right_branch but not left_branch |
| `files_modified` | Metric | Files present in both but with different content |
| `files_deleted` | Metric | Files present in left_branch but not right_branch |
| `files_other` | Metric | Files with unrecognised change type |
| `distinct_authors` | Metric | Number of distinct last-commit authors in the drift set |
| `earliest_change_date` | Timestamp | Date of the oldest last-commit among differing files |
| `latest_change_date` | Timestamp | Date of the most recent last-commit among differing files |

---

## Related

- `Instructions/Building the Commit Drift Dashboard.md` — commit-based branch drift
- `Instructions/Building the Env Drift Summary Dashboard.md` — BigQuery/GCS schema drift
- `Instructions/Building the Looker Studio Dashboards.md` — full 4-page dashboard guide
- `Instructions/Building the Management Dashboard.md` — executive red/green health grid
- `TEF remediation/looker_sql/file_drift_report.sql` — reference SQL (no `run_number`; not used as data source)
- `TEF remediation/Terraform/BQ DS + Tables.tf` — `file_drift_report` view definition,
  `branch_drift_kpis` and `branch_drift_evidence` schema definitions
