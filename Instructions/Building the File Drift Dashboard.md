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
6. **Leave "Enable date range parameters" unchecked.** The query uses a fixed 90-day
   lookback window and does not use `@DS_START_DATE`/`@DS_END_DATE` parameters. Checking
   this box would cause an error.
7. Name the data source `File Drift`.
8. Click **Add** (top right) → **Add to Report**.

> **Which query to paste:** The file contains two query blocks. The active one starts with
> `WITH latest_exec AS (` and ends with `ORDER BY ks.severity_sort, ks.unique_files DESC, ...`.
> Everything after the first `/* ---- */` divider is the commented-out drill-through query —
> do not include it.

---

## Step 2 — Set field types

1. Click **Resource → Manage added data sources → pencil icon** on `File Drift`.
2. Set the following:

   | Field | Change to |
   |---|---|
   | `run_date` | **Date** (day-level) — used by the Run date dropdown filter |
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

### Filter 1 — Run date

1. **Insert → Filter control**.
2. Field: `run_date`. Control type: **Drop-down list**. Label: `Run date`.
3. The dropdown lists every date on which a successful file drift run was recorded
   (up to 90 days back). Selecting one date shows the snapshot from that run.
4. Leaving the filter empty shows all runs combined.

> **"Enable date range parameters" must be UNCHECKED** on the `File Drift` data source.
> The SQL uses a fixed 90-day lookback window — it does not use Looker Studio date
> parameters.

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

> To make all four controls apply to every chart: select each control → right panel →
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
- `TEF remediation/looker_sql/file_drift_report.sql` — the SQL query used as data source
- `TEF remediation/Terraform/BQ DS + Tables.tf` — `branch_drift_kpis` and
  `branch_drift_evidence` schema definitions
