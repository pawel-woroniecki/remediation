# One-off utility scripts

These are standalone scripts intended to be run manually from **Cloud Shell** (or any
shell authenticated to GCP). They are not deployed to Cloud Run and have no scheduler.

---

## Prerequisites

All scripts assume:
- `gcloud` CLI installed and authenticated (`gcloud auth login` or Cloud Shell default)
- Python 3.11+ with the project's standard GCP libraries available
- Sufficient IAM permissions (noted per script)

---

## Scripts

### 1. `backfill_env_drift_report_links.py`

**Purpose**
Backfills the `gcs_report_path` column in `devops_reports.env_drift_findings` for
historical execution rows where the field is `NULL`. It lists all `report.md` files
stored in the GCS reports bucket, reconstructs the HTTPS URL for each execution ID,
and writes the URLs to BigQuery via a MERGE statement.

This is needed because older versions of the env_drift scanner wrote findings to BQ
without populating `gcs_report_path`. The `env_drift_summary` BQ view (used by the
Looker Studio dashboard) reads this field to produce the "Report link" column — after
running this script the historical rows will show clickable links.

**IAM required**
- `roles/bigquery.dataEditor` on `devops_reports.env_drift_findings`
- `roles/storage.objectViewer` on the reports GCS bucket

**Run**
```bash
cd ~/remediation
python "TEF remediation/scripts/backfill_env_drift_report_links.py" \
  --bucket tefde-gcp-fastoss-dev-gcs-devops-reports \
  --prefix env-drift \
  --reporting-project tefde-gcp-fastoss-dev
```

**Output**
Prints the number of executions found in GCS, the number of findings rows with NULL
`gcs_report_path`, and the number of rows updated. Safe to re-run — the MERGE only
touches rows where `gcs_report_path IS NULL`.

---

### 2. `copy_composer_dags.py`

**Purpose**
Clones the `dags/` folder from the production Composer GCS bucket into the `dags2/`
folder of the test or dev Composer bucket. The full nested folder structure is preserved.
YAML files (`.yml` / `.yaml`) have every occurrence of the word `"prod"` replaced with
`"test"` or `"dev"` before upload. All other file types are copied server-side without
downloading.

**IAM required**
- `roles/storage.objectViewer` on the production bucket (to read)
- `roles/storage.objectAdmin` on the target bucket (to write)

**Run**
```bash
cd ~/remediation

# Copy prod → test (dry run first to preview)
python "TEF remediation/scripts/copy_composer_dags.py" --target test --dry-run
python "TEF remediation/scripts/copy_composer_dags.py" --target test

# Copy prod → dev
python "TEF remediation/scripts/copy_composer_dags.py" --target dev
```

If the actual GCS bucket name differs from the default (e.g. includes a hash suffix),
override with `--src-bucket` / `--dst-bucket`:
```bash
python "TEF remediation/scripts/copy_composer_dags.py" \
  --target     test \
  --src-bucket europe-west3-fastoss-prod-composer-3-abc123-bucket \
  --dst-bucket europe-west3-fastoss-test-composer-3-def456-bucket
```

**Output**
Prints one line per file (`[yaml]` or `[copy]`) and a final summary count.

---

### 3. `composer_dag_status_report.py`

**Purpose**
Produces a snapshot report of the latest run status for every DAG in every Cloud
Composer environment in a GCP project. For each DAG it shows the name, whether it is
paused, the last run state (`success` / `failed` / `running` / `queued` / `no_runs`),
the execution timestamp, and a direct link to the Airflow UI for that specific run.

**IAM required**
- `roles/composer.user` (covers both environment discovery and Airflow webserver access
  through IAP)

**Run**
```bash
cd ~/remediation
python "TEF remediation/scripts/composer_dag_status_report.py"
```

All parameters have sensible defaults. Override any of them if needed:
```bash
python "TEF remediation/scripts/composer_dag_status_report.py" \
  --project     tefde-gcp-fastoss-prod-gke \
  --location    europe-west3 \
  --environment fastoss-prod-composer-3 \
  --output      dag_report.csv
```

**Output**
- Live terminal progress with status emoji per DAG
- `dag_status_report.csv` (default) containing: `environment`, `location`, `dag_id`,
  `is_paused`, `latest_run_state`, `execution_date`, `run_id`, `airflow_ui_link`,
  `console_link`

Import the CSV into **Google Sheets** (`File → Import`) to get clickable links in the
`airflow_ui_link` column that open directly in the Airflow UI.
