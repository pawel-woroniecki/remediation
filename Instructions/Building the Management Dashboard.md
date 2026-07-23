# Building the Management Dashboard in Looker Studio

This document explains how to build the executive red/green health grid — a single-page
dashboard that shows the drift status of all repositories across four report types, designed
for senior managers who need a quick pass/fail view rather than raw numbers.

---

## What the dashboard shows

| Column | Source | Meaning |
|---|---|---|
| `repository` | All reports | GitLab project name |
| `GCP` | env_drift | BigQuery drift findings count |
| `GCS` | env_drift | GCS drift findings count |
| `Branch drift` | commit_drift | Total unique commits across all branch comparisons |
| `File drift` | file_drift | Total unique files across all branch comparisons |

Each cell shows a green dot (●) when the value is zero, or the count in red when greater than
zero. Three filter controls let managers narrow the view by date, run, and overall status.

---

## Prerequisites

- `terraform apply` has been run (the `management_dashboard` view must exist in BigQuery).
- At least one execution of all four report jobs has completed (env_drift, commit_drift,
  file_drift) — the view joins all three and needs data from each.
- A `telefonica.de` Google account with read access to `tefde-gcp-fastoss-dev`.

---

## Step 1 — Create the report and connect the data source

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com) and sign in.
2. Click **Create → Report**.
3. In the data source picker choose **BigQuery**.
4. Navigate: **My Projects → `tefde-gcp-fastoss-dev` → `devops_reports` →
   `management_dashboard`**.
5. Click **Add** (top right) → **Add to Report**.

---

## Step 2 — Set field types

1. Click **Resource → Manage added data sources → pencil icon** on `management_dashboard`.
2. Set the following types:

   | Field | Change to |
   |---|---|
   | `run_number` | **Number** with **No aggregation** (make it a Dimension, not a Metric) |
   | `status` | **Text** — confirm it is already a Dimension |
   | `bq_findings` | **Number**, Aggregation: **Sum** |
   | `gcs_findings` | **Number**, Aggregation: **Sum** |
   | `branch_drift` | **Number**, Aggregation: **Sum** |
   | `file_drift` | **Number**, Aggregation: **Sum** |

3. Click **Done → Close**.

---

## Step 3 — Create the four calculated fields

The calculated fields convert numeric counts into a display string: a green dot when zero, the
number when non-zero. This is what drives the red/green colour formatting.

For each of the four metrics, create a calculated field:

1. Click **Resource → Manage added data sources → pencil icon**.
2. Click **Add a field** (bottom left).
3. Create the following four fields:

**Field 1 — GCP**
- Field name: `GCP`
- Formula:
  ```
  IF(bq_findings = 0, "●", TEXT(bq_findings))
  ```

**Field 2 — GCS**
- Field name: `GCS`
- Formula:
  ```
  IF(gcs_findings = 0, "●", TEXT(gcs_findings))
  ```

**Field 3 — Branch drift**
- Field name: `Branch drift`
- Formula:
  ```
  IF(branch_drift = 0, "●", TEXT(branch_drift))
  ```

**Field 4 — File drift**
- Field name: `File drift`
- Formula:
  ```
  IF(file_drift = 0, "●", TEXT(file_drift))
  ```

4. Click **Done → Close** after creating all four fields.

---

## Step 4 — Build the table

1. **Insert → Table**.
2. In the **Setup** panel, set:
   - **Dimensions:** `repository`, `run_number`, `GCP`, `GCS`, `Branch drift`, `File drift`
   - **Metrics:** *(none — remove any that Looker Studio adds automatically)*
   - **Sort:** `repository` ascending
   - **Rows per page:** `50`

   > **Important:** all six fields must be in **Dimensions**, not Metrics. The four calculated
   > fields are text strings — placing them in Metrics would aggregate them as Count Distinct
   > and break the display entirely.

3. **Date range dimension:** in the Setup panel scroll down to **Date range dimension** and set
   it to `run_date`. This connects the table to the date range filter control.

---

## Step 5 — Apply conditional formatting

This is what makes cells appear green or red.

1. With the table selected, click the **Style** tab in the right panel.
2. Scroll down to **Conditional formatting** and click **Add**.
3. Add the following rules for **each** of the four calculated fields (`GCP`, `GCS`,
   `Branch drift`, `File drift`). Repeat the process four times:

   **Rule A — green for zero:**
   - Apply to: the calculated field (e.g. `GCP`)
   - Condition: **Text contains** → `●`
   - Font color: `#1B8A00` (dark green)
   - Background: *(leave default or set to a very light green `#E8F5E9` for extra contrast)*

   **Rule B — red for non-zero:**
   - Apply to: the same calculated field
   - Condition: **Text does not contain** → `●`
   - Font color: `#C62828` (dark red)
   - Font style: **Bold**

4. After applying all rules, the table should show green dots for clean repositories and red
   counts for repositories with findings.

---

## Step 6 — Add filter controls

Insert three controls above the table:

### Filter 1 — Date range

1. **Insert → Date range control**.
2. Set **Default date range** to **Yesterday**.
3. The control automatically binds to the `run_date` field (set as Date range dimension in
   Step 4).

### Filter 2 — Run number

1. **Insert → Filter control**.
2. Field: `run_number`.
3. Control type: **Drop-down list**.
4. Label: `Run`.
5. Use this to switch between Run 1 and Run 2 on days when the env_drift job was re-triggered.

### Filter 3 — Status (the show-all toggle)

1. **Insert → Filter control**.
2. Field: `status`.
3. Control type: **Drop-down list**.
4. Label: `Status`.
5. This is the key toggle for managers:
   - **All** → shows all repositories including fully green ones
   - **Has findings** → shows only repositories with at least one non-zero metric
   - **All clear** → shows only fully green repositories (useful for confirming clean repos)

> To make all three controls apply to the table: select each control → right panel →
> **Filter** section → confirm **All charts on this page** is selected.

---

## Step 7 — Optional: add summary scorecards

Four scorecard tiles at the top give a single-number total for the selected filters.

1. **Insert → Scorecard**. Metric: `bq_findings`, Aggregation: **SUM**. Label: `BQ findings`.
2. **Insert → Scorecard**. Metric: `gcs_findings`, Aggregation: **SUM**. Label: `GCS findings`.
3. **Insert → Scorecard**. Metric: `branch_drift`, Aggregation: **SUM**. Label: `Branch drift`.
4. **Insert → Scorecard**. Metric: `file_drift`, Aggregation: **SUM**. Label: `File drift`.
5. Arrange them in a row above the table.

---

## Step 8 — Share

1. Click **Share** (top right).
2. Add the management team or Google Group.

For organisation-wide access where viewers do not need their own GCP permissions, follow the
**Step 0 — One-time GCP setup for Service Account Credentials** instructions in
`Instructions/Building the Looker Studio Dashboards.md`.

---

## What the finished dashboard looks like

| repository | Run | GCP | GCS | Branch drift | File drift |
|---|---|---|---|---|---|
| operations_auxiliary | 1 | **3** | ● | **12** | ● |
| operations_mobile | 1 | ● | ● | ● | ● |
| perf_mgmt_ip | 1 | ● | **1** | ● | **4** |
| ndl_core_base | 1 | ● | ● | ● | ● |

Numbers appear in red bold; dots appear in green. Selecting **Status = Has findings** hides
the all-green rows so only problem repositories remain visible.

---

## Data source field reference

| Field | Type | Description |
|---|---|---|
| `repository` | Dimension | GitLab project name |
| `run_date` | Date dimension | Date of the run — use as the date range filter field |
| `run_number` | Dimension | Sequential env-drift run number per day (1 = first run). All-green repos that had no env-drift findings are assigned run_number = 1. |
| `bq_findings` | Metric | BigQuery drift finding count |
| `gcs_findings` | Metric | GCS drift finding count |
| `branch_drift` | Metric | Total unique commits across all branch comparisons (commit drift) |
| `file_drift` | Metric | Total unique files across all branch comparisons (file drift) |
| `status` | Dimension | `All clear` when all four metrics = 0; `Has findings` otherwise |
| `GCP` | Calculated | `"●"` when bq_findings = 0, otherwise the count as text |
| `GCS` | Calculated | `"●"` when gcs_findings = 0, otherwise the count as text |
| `Branch drift` | Calculated | `"●"` when branch_drift = 0, otherwise the count as text |
| `File drift` | Calculated | `"●"` when file_drift = 0, otherwise the count as text |

---

## Related

- `Instructions/Building the Env Drift Summary Dashboard.md` — detailed env-drift dashboard
  with report links
- `Instructions/Building the Looker Studio Dashboards.md` — full 4-page dashboard guide and
  one-time GCP service account setup
- `TEF remediation/Terraform/BQ DS + Tables.tf` — `management_dashboard` view definition
