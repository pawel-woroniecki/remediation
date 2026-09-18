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
- `terraform apply` has been run and the `commit_drift_report` view exists in `devops_reports`
  (verify: `SELECT * FROM tefde-gcp-fastoss-dev.devops_reports.commit_drift_report LIMIT 1`).
- A `telefonica.de` Google account with read access to `tefde-gcp-fastoss-dev`.

---

## Step 1 — Create the report and connect the data source

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com) and sign in.
2. Click **Create → Report**.
3. In the data source picker choose **BigQuery → My Projects**.
4. Select **`tefde-gcp-fastoss-dev` → `devops_reports` → `commit_drift_report`**.
5. **Leave "Enable date range parameters" unchecked.** The view uses a fixed 90-day
   lookback window and does not use `@DS_START_DATE`/`@DS_END_DATE` parameters. Checking
   this box would cause an error.
6. Name the data source `Commit Drift`.
7. Click **Add** (top right) → **Add to Report**.

> The `commit_drift_report` view is defined in `TEF remediation/Terraform/BQ DS + Tables.tf`
> and includes a `run_number` field (1 = latest run for that date, 2 = previous run, …).
> The SQL file `TEF remediation/looker_sql/commit_drift_report.sql` is kept as reference only —
> it does not include `run_number` and is no longer the primary data source.

---

## Step 2 — Set field types

1. Click **Resource → Manage added data sources → pencil icon** on `Commit Drift`.
2. Set the following:

   | Field | Change to |
   |---|---|
   | `run_date` | **Date** (day-level) — this is the field used by the Run date dropdown filter |
   | `run_number` | **Number**, Aggregation: **None** — used by the Run number dropdown filter |
   | `execution_ts` | **Date & Time** |
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

## Step 4 — Add the pivot table (drift directions as columns)

This is the primary at-a-glance view: one row per repo, one column per drift direction,
cells showing `unique_commits`. The three critical directions are automatically labelled
with ⚠ by the BQ view.

1. **Insert → Pivot table**.
2. In the **Setup** panel, set:
   - **Row dimension:** `repo`
   - **Column dimension:** `drift_direction`
   - **Metric:** `unique_commits` (SUM)
3. **Sort** (rows): `unique_commits` descending — most-drifted repos appear first.
4. **Style → Column total**: Off (totals are not meaningful across directions).
5. **Style → Heatmap**: On — colour-codes cells by value so high counts stand out.

> **Column order:** Looker Studio sorts pivot columns alphabetically by the dimension value.
> The ⚠ character (Unicode U+26A0) sorts before ASCII letters in BigQuery's collation, so
> the three critical columns appear on the left automatically:
> `⚠ production not in master` · `⚠ production not in test` · `⚠ test not in master`
> followed by `master not in test` · `test not in production`.
> You can drag column headers to reorder them if needed.

> The flat table from Step 3 remains useful for drill-down (it shows authors and commit
> dates per row). The pivot gives the cross-direction summary at a glance.

---

## Step 5 — Add a bar chart: top repos by commit drift

1. **Insert → Bar chart**.
2. Setup:
   - **Dimension:** `repo`
   - **Metric:** `unique_commits` (SUM)
   - **Sort:** `unique_commits` descending
   - **Number of rows:** `15`
3. This gives a quick view of which repos have the most out-of-sync commits.

---

## Step 6 — Add filter controls

Insert these five controls above the table and pivot table:

### Filter 1 — Run date

1. **Insert → Filter control**.
2. Field: `run_date`. Control type: **Drop-down list**. Label: `Run date`.
3. The dropdown lists every date on which a successful commit drift run was recorded
   (up to 90 days back). Selecting one date shows the snapshot from that run.
4. Leaving the filter empty (no selection) shows all runs combined — useful to see
   which repos appear across all recent runs, but not the normal usage.

> **Single-date behavior:** Because the view returns one result row per repo × direction
> × run, picking a single date in this dropdown is equivalent to "show me the state
> as of this run." There is no date range picker — Looker Studio's built-in Date Range
> control would always show two calendar pickers (start + end), which is misleading
> for a per-snapshot report. The dropdown is the correct control here.
>
> **"Enable date range parameters" must be UNCHECKED** on the `Commit Drift` data
> source. The view uses a fixed 90-day lookback window — it does not use
> `@DS_START_DATE`/`@DS_END_DATE` parameters.

### Filter 2 — Run number

1. **Insert → Filter control**.
2. Field: `run_number`. Control type: **Drop-down list**. Label: `Run (1 = latest)`.
3. When the job runs more than once in a day (e.g. a scheduled run at 05:20 and a manual
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
3. Use this to show only `high` or `medium` severity rows and ignore clean ones.

### Filter 5 — Drift direction

1. **Insert → Filter control**.
2. Field: `drift_direction`. Control type: **Drop-down list**. Label: `Direction`.
3. Useful when a repo is compared in both directions (e.g. main→develop and develop→main)
   and you want to focus on one.

> To make all five controls apply to every chart: select each control → right panel →
> **Filter** section → confirm **All charts on this page** is selected.

---

## Step 7 — Optional: add summary scorecards

Three scorecard tiles at the top give a single-number total for the selected filters.

1. **Insert → Scorecard**. Metric: `unique_commits` (SUM). Label: `Drifted commits`.
2. **Insert → Scorecard**. Metric: `unique_files` (SUM). Label: `Files affected`.
3. **Insert → Scorecard**. Metric: `distinct_authors` (SUM). Label: `Authors`.
4. Arrange them in a row above the controls.

---

## Step 8 — Add the commit staleness table

This table answers the question *"how old are these waiting commits?"* — surfacing
drift directions where unmerged commits have been sitting for weeks or months.

### Prerequisites

`terraform apply` must have been run after the `branch_drift_staleness` view was added
to `BQ DS + Tables.tf`. Verify the view exists:

```sql
SELECT * FROM `tefde-gcp-fastoss-dev.devops_reports.branch_drift_staleness`
ORDER BY days_oldest_waiting DESC LIMIT 5;
```

### Connect the data source

1. In Looker Studio edit mode, click **Add data** (top toolbar).
2. Choose **BigQuery → My Projects → `tefde-gcp-fastoss-dev` → `devops_reports` →
   `branch_drift_staleness`**.
3. Click **Add** → **Add to Report**.
4. Name the data source `Commit Staleness`.

> **"Enable date range parameters"** must be **unchecked** on the connector screen
> (same rule as the Job Run Status dashboard — see
> `Instructions/Building the Job Run Status Dashboard.md`).

### Set field types

In **Resource → Manage added data sources → pencil icon** on `Commit Staleness`:

| Field | Type | Default Aggregation |
|---|---|---|
| `repo` | Text | None |
| `drift_direction` | Text | None |
| `snapshot_date` | Date | None |
| `oldest_commit_date` | Date & Time | None |
| `newest_commit_date` | Date & Time | None |
| `commits_waiting` | Number | Sum |
| `days_oldest_waiting` | Number | Max |

Click **Done → Close**.

### Build the table

1. **Insert → Table**.
2. In the **Setup** panel, set all columns as **Dimensions** (no Metrics):
   - **Dimensions:** `repo`, `drift_direction`, `days_oldest_waiting`,
     `oldest_commit_date`, `newest_commit_date`, `commits_waiting`
3. **Do NOT set a Date range dimension** — leave it blank/None.
4. **Sort:** `days_oldest_waiting` descending — stalest repos appear first.
5. **Rows per page:** 50.

> **Why no Date range dimension?** The `branch_drift_staleness` view always computes the
> globally latest run per repo × direction (`MAX(run_date)`). It is designed to answer
> *"which repos have stale commits right now?"* — not *"what was the state on date X?"*.
> If you set a Date range dimension and filter to a past date, the table returns almost
> no rows (only repos whose last-ever run was on that exact date). Leaving the Date range
> dimension blank means the page-level date control is ignored for this table and it
> always shows the current state, which is the correct behaviour.

### Add conditional formatting on `days_oldest_waiting`

1. With the table selected → **Style** tab → scroll to **Conditional formatting**.
2. Add two rules on the `days_oldest_waiting` dimension:

| Condition | Format |
|---|---|
| Number **≥ 30** | Background `#FDECEA` (light red), text `#C62828` (dark red), **Bold** |
| Number **≥ 7** | Background `#FFF8E1` (light amber), text `#E65100` (orange) |

Rows where the oldest waiting commit is over a month old will appear in red; those
over a week old in amber; recent commits are unformatted.

### Interpretation

| `drift_direction` | Meaning of a high `days_oldest_waiting` value |
|---|---|
| `test not in production` | Commits approved in test but blocked from prod — merge delay or freeze |
| `production not in master` | Hotfixes applied to prod but not back-ported — risk of regression on next deploy |
| `master not in test` | New development not promoted to test — pipeline stall |

---

## Step 9 — Share

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

### `Commit Drift` data source (main KPI table)

| Field | Type | Description |
|---|---|---|
| `run_date` | Date dimension | Calendar date of the run (Europe/Berlin) — use as the Run date dropdown filter field |
| `run_number` | Number | 1 = latest run for that date, 2 = previous run — use as the Run number dropdown filter field |
| `execution_ts` | Date & Time | Full run start timestamp |
| `environment` | Dimension | GCP environment label |
| `triggered_by` | Dimension | Email or identity that triggered the run |
| `repo` | Dimension | GitLab project name |
| `drift_direction` | Dimension | Direction label: `<right_branch> not in <left_branch>`. The three critical directions are prefixed with ⚠: `⚠ test not in master`, `⚠ production not in test`, `⚠ production not in master`. |
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

### `Commit Staleness` data source (`branch_drift_staleness` view)

| Field | Type | Description |
|---|---|---|
| `repo` | Dimension | GitLab project name |
| `drift_direction` | Dimension | e.g. `test_not_in_production` |
| `snapshot_date` | Date dimension | Date of the most recent run for this repo/direction |
| `commits_waiting` | Metric | Number of distinct commits in this direction |
| `oldest_commit_date` | Timestamp | Author date of the oldest unmerged commit |
| `newest_commit_date` | Timestamp | Author date of the most recent unmerged commit |
| `days_oldest_waiting` | Metric | Days between `oldest_commit_date` and `run_date` — the staleness indicator |

---

## Related

- `Instructions/Building the File Drift Dashboard.md` — file-content branch drift (which files
  differ, by change type: added / modified / deleted)
- `Instructions/Building the Env Drift Summary Dashboard.md` — BigQuery/GCS schema drift
- `Instructions/Building the Looker Studio Dashboards.md` — full 4-page dashboard guide and
  one-time GCP service account setup
- `Instructions/Building the Management Dashboard.md` — executive red/green health grid
- `TEF remediation/looker_sql/commit_drift_report.sql` — reference SQL (no `run_number`; not used as data source)
- `TEF remediation/Terraform/BQ DS + Tables.tf` — `commit_drift_report` view definition,
  `branch_drift_kpis`, `branch_drift_evidence`, and `branch_drift_staleness` schema definitions
