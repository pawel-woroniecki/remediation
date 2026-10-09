# Building the File Drift Details Dashboard in Looker Studio

This document explains how to build the File Drift Details dashboard — a per-file
table showing exactly which files differ between branches, who last changed them,
and when.  End users can use this dashboard to identify which files need remediation.

This dashboard complements the **File Drift** dashboard (which shows per-repository
KPI counts) by drilling down to the individual file level.

---

## What the dashboard shows

| Column | Description |
|---|---|
| `repo` | GitLab project name |
| `drift_direction` | e.g. `production differs from test` — branches being compared |
| `file_path` | Path of the drifting file relative to the repo root |
| `change_label` | `added` / `modified` / `deleted` / `other` — how the file differs |
| `last_author` | Person who last committed a change to this file on the right branch |
| `last_changed_at` | Timestamp of that last commit |
| `last_commit_sha` | Short git SHA of the last commit — for traceability |

---

## Prerequisites

- At least one `devops-reports-file-drift` Cloud Run Job execution has completed
  successfully (so `branch_drift_evidence` has data).
- `terraform apply` has been run and the `file_drift_evidence_report` view exists
  in `devops_reports`
  (verify: `SELECT * FROM tefde-gcp-fastoss-dev.devops_reports.file_drift_evidence_report LIMIT 1`).
- A `telefonica.de` Google account with read access to `tefde-gcp-fastoss-dev`.

---

## Step 1 — Create the report and connect the data source

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com) and sign in.
2. Click **Create → Report**.
3. In the data source picker choose **BigQuery → My Projects**.
4. Select **`tefde-gcp-fastoss-dev` → `devops_reports` → `file_drift_evidence_report`**.
5. Leave all options at their defaults and click **Connect**.
6. Name the data source `File Drift Details`.
7. Click **Add** (top right) → **Add to Report**.

> Date filtering is handled by setting **Date range dimension** to `run_date` on each
> chart and adding a **Date Range Control** to the page (see Step 5). The "Enable date
> range parameters" option is not available for direct view connections — it only appears
> in Custom Query mode.
>
> The view is defined in `TEF remediation/Terraform/BQ DS + Tables.tf`.
> The SQL reference file is `TEF remediation/looker_sql/file_drift_evidence_report.sql`.

---

## Step 2 — Set field types

1. Click **Resource → Manage added data sources → pencil icon** on `File Drift Details`.
2. Set the following:

   | Field | Change to |
   |---|---|
   | `run_date` | **Date** (day-level) — used by the Run date dropdown filter |
   | `run_number` | **Number**, Aggregation: **None** |
   | `execution_ts` | **Date & Time** |
   | `last_changed_at` | **Date & Time** |

3. The remaining fields (`repo`, `drift_direction`, `discrepancy`, `file_path`,
   `change_label`, `raw_change_type`, `last_author`, `last_commit_sha`,
   `problem_statement`, `environment`, `triggered_by`) should already be
   **Text** dimensions — confirm and leave unchanged.

4. Click **Done → Close**.

---

## Step 3 — Build the main table

1. **Insert → Table**.
2. In the **Setup** panel set:
   - **Dimensions:** `repo`, `drift_direction`, `file_path`, `change_label`, `last_author`
   - **Metrics:** `last_changed_at` (set aggregation to **None** or **Max**)
   - **Sort:** `repo` ascending, then `drift_direction`, then `file_path` ascending.
   - **Rows per page:** `100`.
   - **Date range dimension:** `run_date` — connects this table to the Date Range Control.

> Each row is one drifting file.  For `integration_layer` + `production differs from test`
> you will see 50 rows — one per file that differs.

---

## Step 4 — Add a bar chart: file count by change type per repo

1. **Insert → Bar chart** (stacked).
2. Setup:
   - **Dimension:** `repo`
   - **Breakdown dimension:** `change_label`
   - **Metric:** `Record Count` (or `COUNT(file_path)`)
   - **Sort:** Record Count descending
   - **Number of rows:** `15`
3. This shows, per repository, how many files were added vs modified vs deleted —
   helping to prioritise remediation effort.

---

## Step 5 — Add filter controls

Insert these controls above the table and bar chart.

### Filter 0 — Date range

1. **Insert → Date range control**.
2. Set a default range such as **Last 30 days**.
3. This control works via the **Date range dimension** (`run_date`) set on each chart.
   Looker Studio automatically filters the query to the chosen period.

### Filter 1 — Run date

1. **Insert → Filter control**.
2. Field: `run_date`. Control type: **Drop-down list**. Label: `Run date`.
3. The dropdown lists every date within the Date Range Control window on which a
   successful run was recorded. Select a specific date to see the snapshot from that run.

### Filter 2 — Run number

1. **Insert → Filter control**.
2. Field: `run_number`. Control type: **Drop-down list**. Label: `Run (1 = latest)`.
3. Use `1` for the most recent run of the selected date; `2` for the previous run
   if the job ran more than once that day.

### Filter 3 — Drift direction

1. **Insert → Filter control**.
2. Field: `drift_direction`. Control type: **Drop-down list**. Label: `Drift direction`.
3. Use this to focus on a single direction (e.g. `production differs from test`).

### Filter 4 — Repository

1. **Insert → Filter control**.
2. Field: `repo`. Control type: **Drop-down list**. Label: `Repository`.

> To make all filters apply to every chart: select each control → right panel →
> **Filter** section → confirm **All charts on this page** is selected.

---

## Step 6 — Add summary scorecards

Four scorecard tiles at the top give a total count for the selected filters.

1. **Insert → Scorecard**. Metric: `Record Count`. Label: `Files drifting`.
2. **Insert → Scorecard**. Metric: `Record Count`. Add filter: `change_label = added`. Label: `Files added`.
3. **Insert → Scorecard**. Metric: `Record Count`. Add filter: `change_label = modified`. Label: `Files modified`.
4. **Insert → Scorecard**. Metric: `Record Count`. Add filter: `change_label = deleted`. Label: `Files deleted`.

> To add a metric-level filter on a scorecard: select the scorecard → Setup tab →
> click **Add a filter** → Create a filter on `change_label` equals the target value.

---

## Step 7 — Conditional formatting on change type

1. Select the main table → **Style** tab → **Conditional formatting**.
2. Add rules on the `change_label` dimension:

| Condition | Format |
|---|---|
| Text **is** `added` | Background `#E8F5E9` (light green), text `#2E7D32` (dark green) |
| Text **is** `modified` | Background `#FFF8E1` (light amber), text `#E65100` (orange) |
| Text **is** `deleted` | Background `#FDECEA` (light red), text `#C62828` (dark red) |

---

## Step 8 — Share

1. Click **Share** (top right).
2. Add the team or Google Group.

For organisation-wide access where viewers do not need their own GCP permissions,
follow the **Step 0 — One-time GCP setup for Service Account Credentials**
instructions in `Instructions/Building the Looker Studio Dashboards.md`.

---

## How to use the dashboard for remediation

1. Set the **Drift direction** filter to `production differs from test` (or another
   direction relevant to your work).
2. Set the **Run date** filter to today (or the most recent run date).
3. The table now shows every file that differs — with who last changed it and when.
4. Files marked `added` exist on production but not on test — they need to be
   propagated to test (or investigated if they should not be there).
5. Files marked `modified` have different content — sync the correct version to the
   target branch.
6. Files marked `deleted` exist on test but not on production — check whether this
   is intentional.
7. Use `last_commit_sha` to look up the exact commit in GitLab for context.

---

## Data source field reference

### `File Drift Details` data source

| Field | Type | Description |
|---|---|---|
| `run_date` | Date | Calendar date of the run (Europe/Berlin) |
| `run_number` | Number | 1 = latest run for that date, 2 = previous |
| `execution_ts` | Date & Time | Full run start timestamp |
| `environment` | Dimension | GCP environment label |
| `triggered_by` | Dimension | Identity that triggered the run |
| `repo` | Dimension | GitLab project name |
| `discrepancy` | Dimension | Internal key, e.g. `production_not_in_test` |
| `drift_direction` | Dimension | Human-readable label, e.g. `production differs from test` |
| `file_path` | Dimension | Path of the drifting file within the repo |
| `change_label` | Dimension | `added` / `modified` / `deleted` / `other` |
| `raw_change_type` | Dimension | Raw git letter: A / M / D / R / etc. |
| `last_author` | Dimension | Who last committed to this file on the right branch |
| `last_changed_at` | Date & Time | Timestamp of the last commit touching this file |
| `last_commit_sha` | Dimension | Git commit SHA of the last change |
| `problem_statement` | Dimension | Human-readable description of the drift scenario |

---

## Related

- `Instructions/Building the File Drift Dashboard.md` — KPI-level file drift (per-repo counts)
- `Instructions/Building the Commit Drift Dashboard.md` — commit-based branch drift
- `Instructions/Building the Looker Studio Dashboards.md` — full dashboard guide, service account setup
- `TEF remediation/looker_sql/file_drift_evidence_report.sql` — reference SQL for the data source
- `TEF remediation/Terraform/BQ DS + Tables.tf` — `file_drift_evidence_report` view definition
