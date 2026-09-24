# Looker Studio Dashboard — BQ Structure Drift

Step-by-step instructions for creating the BigQuery Structure Drift dashboard in
Looker Studio. The dashboard shows partitioning and clustering discrepancies across
prod, test, and dev-gke environments, fed by the `compare_bq_structure.py` script.

---

## Prerequisites

Before building the dashboard:

1. **Terraform has been applied** — the `bq_structure_drift` table and
   `bq_structure_drift_report` view must exist in BigQuery:
   ```bash
   cd "TEF remediation/Terraform"
   terraform plan   # confirm 2 new resources are shown
   terraform apply
   ```

2. **At least one script run has completed** — the table must have rows:
   ```bash
   python "TEF remediation/scripts/compare_bq_structure.py" \
     --dataset pl_energy
   ```
   Confirm rows were written:
   ```bash
   bq query --nouse_legacy_sql \
     'SELECT COUNT(*) FROM `tefde-gcp-fastoss-dev.devops_reports.bq_structure_drift`'
   ```

3. **Your Google account has BigQuery access** — Looker Studio uses the dashboard
   creator's own Google identity (no service account key needed). You need at least
   `roles/bigquery.dataViewer` on the `devops_reports` dataset in
   `tefde-gcp-fastoss-dev`.

---

## Step 1 — Create the data source

1. Open [Looker Studio](https://lookerstudio.google.com) and sign in with your
   Capgemini Google account.
2. Click **Create** → **Data source**.
3. In the connector list select **BigQuery**.
4. Under **My Projects**, select project **`tefde-gcp-fastoss-dev`**.
5. Select dataset **`devops_reports`**.
6. Select the view **`bq_structure_drift_report`**.
7. Click **Connect** (top right).
8. On the fields screen:
   - Confirm field types are auto-detected correctly (especially `checked_at` as
     `Date & Time` and `run_number` as `Number`).
   - **Important:** click **Edit connection** → ensure
     **"Enable date range parameters"** is **UNCHECKED**. Without this, Looker
     Studio would push a date range filter into the query and break the `run_number`
     window function.
9. Click **Create Report** (top right).

---

## Step 2 — Configure report settings

1. Give the report a name: click the title **"Untitled Report"** at the top and
   type **BQ Structure Drift**.
2. In **File** → **Report settings**:
   - Timezone: **Europe/Berlin**
   - Currency: leave as default

---

## Step 3 — Add Filter Controls

These two controls let users browse by date and isolate the latest run.

### 3a. Run date filter

1. Click **Add a control** → **Drop-down list**.
2. Drag it to the top of the canvas.
3. In the right-hand panel set:
   - **Control field**: `run_date`
   - **Label**: `Run date`
   - **Default selection**: the most recent date (leave as "None" — Looker Studio
     will show the most recent available value)

### 3b. Run number filter

1. Click **Add a control** → **Drop-down list**.
2. Place it next to the run date filter.
3. In the right-hand panel set:
   - **Control field**: `run_number`
   - **Label**: `Run number (1 = latest)`
   - **Default selection**: `1`

> After adding both filters, all charts below will respond to their selection.
> Filtering to `run_number = 1` shows only the most recent run for each
> dataset/table/attribute combination.

---

## Step 4 — Add Scorecards (summary KPIs)

### 4a. Missing tables count

1. Click **Add a chart** → **Scorecard**.
2. Place it in the top-left of the canvas.
3. Right-panel settings:
   - **Metric**: `Record count` (or `run_id` → COUNT)
   - **Chart-level filter** → **Add filter** → create a new filter:
     - Condition: `discrepancy` **Equal to (=)** `MISSING`
   - **Title**: `Missing tables`
4. Optionally style the number in amber/orange to indicate a warning.

### 4b. Attribute diff count

1. Duplicate the scorecard above (right-click → **Duplicate**).
2. Place it next to the first scorecard.
3. Change the **Chart-level filter** condition to:
   - `discrepancy` **Equal to (=)** `DIFF`
4. Change the **Title** to `Attribute diffs`.
5. Optionally style in red for higher severity.

---

## Step 5 — Add the detail table

1. Click **Add a chart** → **Table**.
2. Resize it to fill most of the canvas width.
3. Right-panel → **Data** tab:
   - **Dimensions**: `dataset_id`, `table_id`, `table_type`, `discrepancy`,
     `attribute`, `prod_value`, `test_value`, `dev_gke_value`
   - **Sort**: `discrepancy` ascending, then `dataset_id` ascending
   - Remove any auto-added metrics
4. Right-panel → **Style** tab:
   - Enable **Row numbers**
   - Enable **Pagination** (25 rows per page)
5. Optional: add conditional formatting on `discrepancy`:
   - `MISSING` → amber background
   - `DIFF` → light red background

---

## Step 6 — Add a bar chart (discrepancies by dataset)

1. Click **Add a chart** → **Bar chart**.
2. Right-panel → **Data** tab:
   - **Dimension**: `dataset_id`
   - **Breakdown dimension**: `discrepancy`
   - **Metric**: `Record count`
   - **Sort**: metric descending
3. Right-panel → **Style** tab:
   - Chart title: `Discrepancies by dataset`
   - Show data labels: on

---

## Step 7 — Add a time-series chart (trend over time)

1. Click **Add a chart** → **Time series**.
2. Right-panel → **Data** tab:
   - **Date dimension**: `run_date`
   - **Breakdown dimension**: `discrepancy`
   - **Metric**: `Record count`
   - **Filter**: add a chart-level filter `run_number` **Equal to (=)** `1`
     (so each date shows only one run's count)
3. Right-panel → **Style** tab:
   - Chart title: `Total discrepancies over time`
   - Show points: on

> This chart is the only one that should **not** be linked to the run_number
> filter control — it intentionally shows one data point per day across all dates.
> To decouple it: right-click the chart → **Chart filter** → toggle off
> **"Apply report-level filter"** for the `run_number` control.

---

## Step 8 — Share the dashboard

1. Click **Share** (top right).
2. Add team members by email or use **"Anyone at Capgemini with the link"**.
3. Set access to **Viewer** for most recipients; **Editor** only for those who
   need to modify the layout.

> Access to the underlying data is controlled by GCP IAM (BigQuery), not by
> Looker Studio sharing. A viewer who lacks `bigquery.dataViewer` on the dataset
> will see a credentials error when they open the dashboard.

---

## Reference

| Item | Value |
|---|---|
| GCP project | `tefde-gcp-fastoss-dev` |
| BigQuery dataset | `devops_reports` |
| Data source (view) | `bq_structure_drift_report` |
| Raw table | `bq_structure_drift` |
| Script | `TEF remediation/scripts/compare_bq_structure.py` |
| Terraform resources | `google_bigquery_table.bq_structure_drift` and `google_bigquery_table.bq_structure_drift_report` in `BQ DS + Tables.tf` |
| Reference SQL | `TEF remediation/looker_sql/bq_structure_drift_report.sql` |
