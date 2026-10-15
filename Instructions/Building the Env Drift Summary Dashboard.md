# Building the Env Drift Summary Dashboard in Looker Studio

This document explains how to build the `env_drift_summary` Looker Studio dashboard — a per-repository table showing BigQuery and GCS drift findings with a clickable link to each run's report file on GCS.

---

## Prerequisites

- `terraform apply` has been run (the `env_drift_summary` view must exist in BigQuery).
- At least one `devops-reports-env-drift` Cloud Run Job execution has completed successfully (so the view has data).
- A `telefonica.de` Google account with read access to `tefde-gcp-fastoss-dev`.

---

## Step 1 — Create the report and connect the data source

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com) and sign in.
2. Click **Create → Report**.
3. In the data source picker choose **BigQuery**.
4. Navigate: **My Projects → `tefde-gcp-fastoss-dev` → `devops_reports` → `env_drift_summary`**.
5. Click **Add** (top right) → **Add to Report**.

---

## Step 2 — Set field types

Before building charts, fix the field types so Looker Studio treats them correctly.

1. Click **Resource → Manage added data sources → pencil icon** on `env_drift_summary`.
2. Find `run_number` — change type from **Number (metric)** to **Number (dimension)** by clicking the aggregation chip and selecting **No aggregation / Dimension**.
3. Find `report_url` — change type to **URL** (click the type icon, select URL). This makes it render as a clickable hyperlink in tables.
4. Click **Done → Close**.

---

## Step 3 — Build the table

1. **Insert → Table**.
2. In the right panel, set:
   - **Dimensions:** `repository`, `run_number`, `report_url`
   - **Metrics:** `bq_findings`, `gcs_findings`
3. Under **Sort**: `repository` ascending (so repos appear alphabetically).
4. Under **Rows per page**: set to **50** (covers all ~42 repos on one screen without paging).
5. To make `report_url` show as a clickable label rather than a raw URL:
   - In the **Style** tab → find the `report_url` column → enable **Hyperlink**.
   - The cell renders as a clickable link that opens in a new tab.

> **Important:** `report_url` must be placed in **Dimensions**, not Metrics. If placed in the Metric bucket, Looker Studio treats it as a number (Count Distinct) and the URL type is lost — you will only be able to choose Number or Currency as the data type, with no hyperlink option.

---

## Step 4 — Add filter controls

Insert these three controls above the table:

### Filter 1 — Date range

1. **Insert → Date range control**.
2. Set **Default date range** to **Yesterday** (shows the most recent daily run by default).
3. Bind it to field `execution_date`.

### Filter 2 — Repository dropdown

1. **Insert → Filter control**.
2. Field: `repository`.
3. Control type: **Drop-down list**.
4. Label: `Repository`.

### Filter 3 — Run number dropdown

1. **Insert → Filter control**.
2. Field: `run_number`.
3. Control type: **Drop-down list**.
4. Label: `Run`.
5. This lets viewers select Run 1 or Run 2 on days when the job was re-triggered.

> To make all three controls apply to the table: select each control → right panel → **Filter** section → confirm **All charts on this page** is selected.

---

## Step 5 — Optional: add summary scorecards

Four scorecard tiles at the top give a single-number view for the selected filters.

1. **Insert → Scorecard**. Metric: `bq_findings`, Aggregation: **SUM**. Label: `BQ findings`.
2. **Insert → Scorecard**. Metric: `gcs_findings`, Aggregation: **SUM**. Label: `GCS findings`.
3. Resize and place them in a row above the table.

---

## Step 6 — Share

1. Click **Share** (top right).
2. Add the team or Google Group.

Viewers do not need their own BigQuery access when the data source uses your personal Google identity. For organisation-wide access where any viewer can open the dashboard without their own GCP permissions, follow the **Step 0 — One-time GCP setup for Service Account Credentials** instructions in `Instructions/Building the Looker Studio Dashboards.md`.

---

## What the finished dashboard looks like

| Repository | Run | BQ findings | GCS findings | Report |
|---|---|---|---|---|
| operations_mobile | 1 | 3 | 0 | Open report |
| perf_mgmt_ip | 1 | 0 | 1 | Open report |
| ndl_core_base | 1 | 0 | 0 | Open report |

Selecting **Run = 1** and **Date = yesterday** shows exactly one row per repository from the most recent scheduled run. The "Open report" link goes directly to the authenticated `report.md` on GCS (`https://storage.cloud.google.com/...`).

---

## Data source field reference

| Field | Type | Description |
|---|---|---|
| `repository` | Dimension | GitLab project name |
| `execution_date` | Date dimension | Date of the run — use as the date range filter field |
| `execution_ts` | Timestamp | Exact run start timestamp |
| `run_number` | Dimension | Sequential run number per repository per day (1 = first run of the day) |
| `bq_findings` | Metric | Number of BigQuery drift findings for this repository and run |
| `gcs_findings` | Metric | Number of GCS drift findings for this repository and run |
| `report_url` | URL | Authenticated GCS link to the `report.md` file for this run |

---

## Related

- `Instructions/Building the Looker Studio Dashboards.md` — combined dashboard guide and one-time GCP service account setup
- `Instructions/Building the Management Dashboard.md` — executive red/green health grid across all report types
- `TEF remediation/Terraform/BQ DS + Tables.tf` — `env_drift_summary` view definition
