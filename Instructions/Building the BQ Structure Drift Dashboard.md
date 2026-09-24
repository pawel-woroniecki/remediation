# Building the BQ Structure Drift Dashboard in Looker Studio

This document explains how to build the BQ Structure Drift Looker Studio dashboard — a
per-table report showing partitioning and clustering discrepancies across prod, test, and
dev-gke environments, for the most recent run or any historical snapshot.

---

## What the dashboard shows

| Column | Description |
|---|---|
| `dataset_id` | BigQuery dataset name |
| `table_id` | BigQuery table name |
| `table_type` | `TABLE`, `VIEW`, `MATERIALIZED_VIEW`, or `EXTERNAL` |
| `discrepancy` | `MISSING` — table absent from one or more lower envs; `DIFF` — table present everywhere but settings differ |
| `attribute` | Which setting differs: `tp_type`, `tp_field`, `tp_expiration_ms`, `tp_require_filter`, `rp_field`, `rp_start`, `rp_end`, `rp_interval`, `clustering`, or `exists` |
| `prod_value` | Value in prod (or `EXISTS` / `ABSENT` for MISSING rows) |
| `test_value` | Value in test |
| `dev_gke_value` | Value in dev-gke |
| `run_date` | Calendar date on which the script ran |
| `run_number` | 1 = latest run for that date, 2 = previous run, … |

---

## Prerequisites

- At least one `compare_bq_structure.py` run has completed successfully (so the
  `bq_structure_drift` table has data). Run it from Cloud Shell if needed:
  ```bash
  python "TEF remediation/scripts/compare_bq_structure.py"
  ```
  Verify rows exist:
  ```sql
  SELECT COUNT(*) FROM `tefde-gcp-fastoss-dev.devops_reports.bq_structure_drift`
  ```
- `terraform apply` has been run and the `bq_structure_drift_report` view exists in
  `devops_reports`
  (verify: `SELECT * FROM tefde-gcp-fastoss-dev.devops_reports.bq_structure_drift_report LIMIT 1`).
- A `telefonica.de` Google account with read access to `tefde-gcp-fastoss-dev`.

---

## Step 1 — Create the report and connect the data source

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com) and sign in.
2. Click **Create → Report**.
3. In the data source picker choose **BigQuery → My Projects**.
4. Select **`tefde-gcp-fastoss-dev` → `devops_reports` → `bq_structure_drift_report`**.
5. **Leave "Enable date range parameters" unchecked.** The view uses a `ROW_NUMBER()`
   window function — checking this box would push a date filter into the query and break
   the `run_number` calculation.
6. Name the data source `BQ Structure Drift`.
7. Click **Add** (top right) → **Add to Report**.

> The `bq_structure_drift_report` view is defined in
> `TEF remediation/Terraform/BQ DS + Tables.tf` and adds `run_date` and `run_number`
> on top of the raw `bq_structure_drift` table.
> The SQL file `TEF remediation/looker_sql/bq_structure_drift_report.sql` is kept as
> reference only — it is not the primary data source.

---

## Step 2 — Set field types

1. Click **Resource → Manage added data sources → pencil icon** on `BQ Structure Drift`.
2. Set the following:

   | Field | Change to |
   |---|---|
   | `run_date` | **Date** (day-level) — used by the Run date dropdown filter |
   | `run_number` | **Number**, Aggregation: **None** — used by the Run number dropdown filter |
   | `checked_at` | **Date & Time** |

3. The remaining fields (`dataset_id`, `table_id`, `table_type`, `discrepancy`,
   `attribute`, `prod_value`, `test_value`, `dev_gke_value`) should already be
   **Text** dimensions — confirm and leave unchanged.
4. Click **Done → Close**.

---

## Step 3 — Add filter controls

Insert these four controls in a row at the top of the canvas.

### Filter 1 — Run date

1. **Insert → Filter control**.
2. Field: `run_date`. Control type: **Drop-down list**. Label: `Run date`.
3. The dropdown lists every date on which `compare_bq_structure.py` ran successfully.
   Selecting one date shows the snapshot from that run.

> **"Enable date range parameters" must be UNCHECKED** on the data source — same rule as
> all other dashboards in this project. The view uses a window function, not a date range
> parameter.

### Filter 2 — Run number

1. **Insert → Filter control**.
2. Field: `run_number`. Control type: **Drop-down list**. Label: `Run (1 = latest)`.
3. When the script runs more than once in a day, `run_number = 1` is the most recent
   run for the selected date. Use together with the Run date filter to compare two runs
   on the same day.

### Filter 3 — Discrepancy type

1. **Insert → Filter control**.
2. Field: `discrepancy`. Control type: **Drop-down list**. Label: `Discrepancy`.
3. Use this to show only `MISSING` rows (tables absent from lower envs) or only `DIFF`
   rows (tables present everywhere but with different settings).

### Filter 4 — Dataset

1. **Insert → Filter control**.
2. Field: `dataset_id`. Control type: **Drop-down list**. Label: `Dataset`.
3. Use this to focus on a single dataset, e.g. `pl_energy`.

> To make all four controls apply to every chart: select each control → right panel →
> **Filter** section → confirm **All charts on this page** is selected.

---

## Step 4 — Add summary scorecards

Three scorecard tiles at the top give a single-number total for the selected filters.

1. **Insert → Scorecard**. Metric: **Record count**. Label: `Total discrepancies`.
2. **Insert → Scorecard**.
   - Metric: **Record count**.
   - **Chart-level filter** → **Add filter** → `discrepancy` **Equal to (=)** `MISSING`.
   - Label: `Missing tables`.
   - Style: amber/orange colour on the number.
3. **Insert → Scorecard**.
   - Metric: **Record count**.
   - **Chart-level filter** → `discrepancy` **Equal to (=)** `DIFF`.
   - Label: `Attribute diffs`.
   - Style: red colour on the number.
4. Arrange the three scorecards in a row above the filters.

---

## Step 5 — Build the main detail table

1. **Insert → Table**.
2. In the **Setup** panel:
   - **Dimensions:** `dataset_id`, `table_id`, `table_type`, `discrepancy`, `attribute`,
     `prod_value`, `test_value`, `dev_gke_value`
   - Remove any auto-added metrics.
   - **Sort:** `discrepancy` ascending (DIFF before MISSING), then `dataset_id` ascending.
   - **Rows per page:** `50`.
3. **Do NOT set a Date range dimension** — the Run date filter control handles date selection.
4. **Style** tab → enable **Row numbers** and **Pagination**.

### Add conditional formatting on `discrepancy`

1. With the table selected → **Style** tab → scroll to **Conditional formatting**.
2. Add two rules on the `discrepancy` dimension:

   | Condition | Background | Text | Style |
   |---|---|---|---|
   | Text **Contains** `MISSING` | `#FFF3E0` (light orange) | `#E65100` (dark orange) | Bold |
   | Text **Contains** `DIFF` | `#FDECEA` (light red) | `#C62828` (dark red) | — |

---

## Step 6 — Add a bar chart: discrepancies by dataset

1. **Insert → Bar chart**.
2. Setup:
   - **Dimension:** `dataset_id`
   - **Breakdown dimension:** `discrepancy`
   - **Metric:** **Record count**
   - **Sort:** metric descending
   - **Number of rows:** `20`
3. **Style** tab → Chart title: `Discrepancies by dataset`. Show data labels: on.

This gives a quick view of which datasets have the most drift and whether they are
mostly MISSING or DIFF type.

---

## Step 7 — Add a time-series chart: trend over time

1. **Insert → Time series**.
2. Setup:
   - **Date dimension:** `run_date`
   - **Breakdown dimension:** `discrepancy`
   - **Metric:** **Record count**
   - **Chart-level filter** → `run_number` **Equal to (=)** `1` (so each date shows
     only the latest run's count, avoiding double-counting on days with multiple runs)
3. **Style** tab → Chart title: `Total discrepancies over time`. Show points: on.

> This chart must be **decoupled from the run_number filter control** — otherwise
> setting `run_number = 1` in the control would conflict with the chart-level filter
> and hide all data. To decouple it: right-click the chart → **Chart filter** →
> toggle off the `run_number` control under **"Filters applied from report-level controls"**.

---

## Step 8 — Share

1. Click **Share** (top right).
2. Add team members by email or use **"Anyone at Capgemini with the link"**.
3. Set access to **Viewer** for most recipients; **Editor** only for those who need to
   modify the layout.

For organisation-wide access where viewers do not need their own GCP permissions, follow
the **Step 0 — One-time GCP setup for Service Account Credentials** instructions in
`Instructions/Building the Looker Studio Dashboards.md`.

---

## What the finished dashboard looks like

| dataset_id | table_id | table_type | discrepancy | attribute | prod_value | test_value | dev_gke_value |
|---|---|---|---|---|---|---|---|
| pl_energy | classic_meter | TABLE | DIFF | tp_type | DAY | DAY | `<none>` |
| pl_energy | classic_meter | TABLE | DIFF | clustering | date,meter_id | date,meter_id | `<none>` |
| pl_weather | weather_site_station_mapping | TABLE | MISSING | exists | EXISTS | EXISTS | ABSENT |
| weather_site | hourly_readings | TABLE | DIFF | tp_field | reading_date | reading_date | `<none>` |

`<none>` means the table exists but has no partitioning or clustering of that type.
`ABSENT` means the table does not exist in that environment.

---

## Data source field reference

### `BQ Structure Drift` data source (`bq_structure_drift_report` view)

| Field | Type | Description |
|---|---|---|
| `run_id` | Dimension | Timestamp-based run identifier, e.g. `20260924T143012Z` |
| `run_date` | Date dimension | Calendar date of the run — use as the Run date dropdown filter field |
| `run_number` | Number | 1 = latest run for that dataset/table/attribute on that date, 2 = previous run |
| `checked_at` | Date & Time | Exact UTC timestamp when the script ran |
| `dataset_id` | Dimension | BigQuery dataset name |
| `table_id` | Dimension | BigQuery table name |
| `table_type` | Dimension | `TABLE`, `VIEW`, `MATERIALIZED_VIEW`, or `EXTERNAL` |
| `discrepancy` | Dimension | `MISSING` or `DIFF` |
| `attribute` | Dimension | Which setting: `tp_type`, `tp_field`, `tp_expiration_ms`, `tp_require_filter`, `rp_field`, `rp_start`, `rp_end`, `rp_interval`, `clustering`, or `exists` |
| `prod_value` | Dimension | Value in prod, or `EXISTS` / `ABSENT` |
| `test_value` | Dimension | Value in test, or `EXISTS` / `ABSENT` |
| `dev_gke_value` | Dimension | Value in dev-gke, or `EXISTS` / `ABSENT` |

---

## Related

- `Instructions/Building the Looker Studio Dashboards.md` — full guide and one-time GCP
  service account setup
- `Instructions/Building the Commit Drift Dashboard.md` — branch commit drift
- `Instructions/Building the Env Drift Summary Dashboard.md` — BQ/GCS env drift
- `Instructions/Building the Management Dashboard.md` — executive red/green health grid
- `TEF remediation/looker_sql/bq_structure_drift_report.sql` — reference SQL
- `TEF remediation/Terraform/BQ DS + Tables.tf` — `bq_structure_drift` table and
  `bq_structure_drift_report` view definitions
- `TEF remediation/scripts/compare_bq_structure.py` — script that populates the table
- `TEF remediation/scripts/README.md` — section 9, script usage and options
