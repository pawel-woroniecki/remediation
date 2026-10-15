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
  `is_paused`, `latest_run_state`, `execution_date`, `run_id`, `airflow_ui_link`

Import the CSV into **Google Sheets** (`File → Import`) to get clickable links in the
`airflow_ui_link` column that open directly in the Airflow UI.

---

### 4. `generate_dataset_mapping.py`

**Purpose**
Cloud Run job entrypoint (report type: `dataset_mapping`). Clones all GitLab repos in
`fastoss_b/ndl_core`, reads the `BQ_DATASET_NAMES` variable from each repo's
`.gitlab-ci.yml`, and writes a JSON file `{dataset_name: repo_name}` to GCS.

The output is consumed by `organize_tf_export.py` (see below) so that Terraform export
files can be sorted into the correct GitLab repository folder without requiring direct
access to GitLab from Cloud Shell.

**When to re-run**
Re-run any time a new repo is added to `ndl_core` or its `BQ_DATASET_NAMES` list
changes.

**IAM required** (Cloud Run service account `devops-reports-runner`)
- `roles/storage.objectAdmin` on the reports GCS bucket
- `roles/secretmanager.secretAccessor` on the `gitlab-token` secret

**Run via Cloud Run job**
```bash
gcloud run jobs execute devops-reports-dataset-mapping \
  --region europe-west3 \
  --project tefde-gcp-fastoss-dev-gke \
  --wait
```

**Inspect the output**
```bash
gsutil cp \
  gs://tefde-gcp-fastoss-dev-gcs-devops-reports/dataset-mapping/dataset_repo_map.json \
  .
cat dataset_repo_map.json | python3 -m json.tool | head -30
```

**Output**
A JSON file at `gs://<reports_bucket>/dataset-mapping/dataset_repo_map.json`:
```json
{
  "il_5gias": "integration_layer",
  "fault_mgmt_core": "fault_mgmt",
  ...
}
```

---

### 5. `organize_tf_export.py`

**Purpose**
One-off script to reorganise the Terraform files produced by
`gcloud beta resource-config bulk-export` into a folder hierarchy that mirrors the
GitLab repository structure.

Each BigQuery resource (dataset, table, routine) is placed under the GitLab repo that
owns its BQ dataset, based on the `dataset_id` attribute read from the `.tf` file
content. Files whose dataset is not claimed by any repo land in `_unmapped/`.

**Output structure**
```
terraform-export-by-repos/
└── prod/
    ├── integration_layer/
    │   ├── BigQueryDataset/
    │   │   └── il-5gias.tf
    │   ├── BigQueryTable/
    │   │   └── il_5gias/
    │   │       ├── table-a.tf
    │   │       └── table-b.tf
    │   └── BigQueryRoutine/
    │       └── il_5gias/
    │           └── routine-a.tf
    ├── fault_mgmt/
    │   └── ...
    └── _unmapped/
        └── BigQueryTable/
            └── shared_dataset/
                └── orphan-table.tf
```

**Prerequisites**
- `gcloud beta resource-config bulk-export` already run; output is in
  `~/tf_export_<env>/` directories (e.g. `~/tf_export_prod/`)
- `dataset_repo_map.json` downloaded from GCS (see step 1 below)
- Python packages: `pip install pyyaml` (only needed for the `--repos-dir` path; not
  required when using `--mapping-file`)

**IAM required** (Cloud Shell user)
- None beyond what is needed to download the mapping file from GCS
  (`roles/storage.objectViewer` on the reports bucket)

**Typical workflow**

Step 1 — generate and download the dataset→repo mapping (one-time or when repos change):
```bash
# Trigger the Cloud Run job
gcloud run jobs execute devops-reports-dataset-mapping \
  --region europe-west3 \
  --project tefde-gcp-fastoss-dev-gke \
  --wait

# Download the mapping file to Cloud Shell
gsutil cp \
  gs://tefde-gcp-fastoss-dev-gcs-devops-reports/dataset-mapping/dataset_repo_map.json \
  .
```

Step 2 — dry run to preview what will be copied:
```bash
cd ~/remediation
python "TEF remediation/scripts/organize_tf_export.py" \
  --mapping-file dataset_repo_map.json \
  --env prod \
  --dry-run
```

Step 3 — run for real:
```bash
python "TEF remediation/scripts/organize_tf_export.py" \
  --mapping-file dataset_repo_map.json \
  --env prod
```

**All options**

| Flag | Default | Description |
|---|---|---|
| `--mapping-file PATH` | _(none)_ | JSON file from the `dataset_mapping` Cloud Run job. When provided, `--repos-dir` is ignored. |
| `--repos-dir PATH` | `/workspace/repos/fastossb` | Local repo clones with `.gitlab-ci.yml` files. Used only if `--mapping-file` is not given. |
| `--base-dir PATH` | `/home/nq10083194` | Parent of `tf_export_*` export directories. |
| `--output-dir PATH` | `{base-dir}/terraform-export-by-repos` | Destination root for the reorganised files. |
| `--env / --envs LIST` | all six | Comma-separated list of environments to process: `prod`, `prod-gke`, `test`, `test-gke`, `dev`, `dev-gke`. |
| `--dry-run` | off | Print what would be copied without writing any files. |

**Examples**

Process a single environment:
```bash
python "TEF remediation/scripts/organize_tf_export.py" \
  --mapping-file dataset_repo_map.json \
  --env prod
```

Process multiple environments at once:
```bash
python "TEF remediation/scripts/organize_tf_export.py" \
  --mapping-file dataset_repo_map.json \
  --env prod,prod-gke
```

Process all six environments:
```bash
python "TEF remediation/scripts/organize_tf_export.py" \
  --mapping-file dataset_repo_map.json
```

Override the export source and output directories:
```bash
python "TEF remediation/scripts/organize_tf_export.py" \
  --mapping-file dataset_repo_map.json \
  --base-dir   /home/myuser \
  --output-dir /home/myuser/tf-by-repo \
  --env prod
```

**Output**
Prints a per-repo file count for each environment and a grand total.
Re-running is safe — files that already exist and are identical (same size and
modification time) are skipped.

---

### 6. `organize_tf_export_flat.py`

**Purpose**
Variant of `organize_tf_export.py` that produces a **flat** folder layout: every
Terraform resource file lands directly in `{env}/{repo}/` instead of in a nested
`BigQueryDataset/` / `BigQueryTable/{dataset}/` subfolder. Resource type and dataset
are encoded in the filename using a prefix:

| Resource type | Filename pattern | Example |
|---|---|---|
| `BigQueryDataset` | `ds_{file}.tf` | `ds_il_5gias.tf` |
| `BigQueryTable` | `t_{dataset}_{file}.tf` | `t_il_5gias_table_a.tf` |
| `BigQueryRoutine` | `r_{dataset}_{file}.tf` | `r_il_5gias_routine_a.tf` |

An `imports.tf` file is auto-generated alongside the resource files for each repo.
It contains one native `import {}` block per resource (without a `module.` prefix),
derived from the `# terraform import TYPE.NAME ID` comments that gcloud bulk-export
embeds in every `.tf` file.

Files whose dataset is not claimed by any repo land in `{env}/_unmapped/` using the
same flat+prefix layout.

Use this variant when you want to work with resources in a single Terraform root
module per repo rather than in nested modules.

**Output structure**
```
terraform-export-flat/
└── prod/
    ├── integration_layer/
    │   ├── ds_il_5gias.tf
    │   ├── t_il_5gias_table_a.tf
    │   ├── t_il_5gias_table_b.tf
    │   ├── r_il_5gias_routine_a.tf
    │   └── imports.tf
    ├── fault_mgmt/
    │   └── ...
    └── _unmapped/
        └── t_shared_dataset_orphan_table.tf
```

**Prerequisites**
Same as `organize_tf_export.py` — see Prerequisites section above.

**Typical workflow**

Step 1 — generate and download the dataset→repo mapping (shared with `organize_tf_export.py`):
```bash
gcloud run jobs execute devops-reports-dataset-mapping \
  --region europe-west3 \
  --project tefde-gcp-fastoss-dev-gke \
  --wait

gsutil cp \
  gs://tefde-gcp-fastoss-dev-gcs-devops-reports/dataset-mapping/dataset_repo_map.json \
  .
```

Step 2 — dry run to preview:
```bash
cd ~/remediation
python "TEF remediation/scripts/organize_tf_export_flat.py" \
  --exports-dir /home/nq10083194/gcp-exports \
  --mapping-file dataset_repo_map.json \
  --env prod \
  --dry-run
```

Step 3 — run for real:
```bash
python "TEF remediation/scripts/organize_tf_export_flat.py" \
  --exports-dir /home/nq10083194/gcp-exports \
  --mapping-file dataset_repo_map.json \
  --env prod
```

**All options**

| Flag | Default | Description |
|---|---|---|
| `--mapping-file PATH` | _(none)_ | JSON file from the `dataset_mapping` Cloud Run job. When provided, `--repos-dir` is ignored. |
| `--repos-dir PATH` | `/workspace/repos/fastossb` | Local repo clones with `.gitlab-ci.yml` files. Used only if `--mapping-file` is not given. |
| `--exports-dir PATH` | _(none)_ | Parent of per-environment export folders named after the env (e.g. `gcp-exports/prod/`). Use this when your export directories are not named `tf_export_{env}`. When provided, `--base-dir` is ignored for locating exports. |
| `--base-dir PATH` | `/home/nq10083194` | Parent of `tf_export_{env}` export directories. Ignored when `--exports-dir` is provided. |
| `--output-dir PATH` | `{base-dir}/terraform-export-flat` | Destination root for the reorganised files. |
| `--env / --envs LIST` | all six | Comma-separated list of environments to process: `prod`, `prod-gke`, `test`, `test-gke`, `dev`, `dev-gke`. |
| `--dry-run` | off | Print what would be copied without writing any files. |

**Output**
Prints a per-repo file count for each environment and a grand total.
Re-running is safe — identical files (same size and modification time) are skipped.

---

### 7. `propagate_tf_env.py`

**Purpose**
Copies the `prod/` output from `organize_tf_export_flat.py` into two sibling
folders — `prod_dev-gke/` and `prod_test/` — substituting the environment token
`prod` throughout every file's content so the Terraform code targets the correct
GCP project, bucket, and group names for each lower environment.

**Replacement rule**

`prod` is replaced only when it appears as a **standalone environment token**, not
as part of a word like `production` or `product`:

| Original | `prod_dev-gke/` | `prod_test/` |
|---|---|---|
| `tefde-gcp-fastoss-prod` | `tefde-gcp-fastoss-dev-gke` | `tefde-gcp-fastoss-test` |
| `fastoss-prod-gcs-reports` | `fastoss-dev-gke-gcs-reports` | `fastoss-test-gcs-reports` |
| `group-prod@domain.com` | `group-dev-gke@domain.com` | `group-test@domain.com` |
| `"production"` | unchanged | unchanged |
| `"product"` | unchanged | unchanged |

> **Note:** If any file references the GKE project `tefde-gcp-fastoss-prod-gke`,
> the substitution will produce `tefde-gcp-fastoss-dev-gke-gke` (wrong). Use
> `--dry-run` to check before applying and fix those lines manually.

**Prerequisites**
- `organize_tf_export_flat.py` has already run and `terraform-export-flat/prod/`
  exists and is populated.

**Run**
```bash
cd ~/remediation

# Preview substitutions first
python "TEF remediation/scripts/propagate_tf_env.py" \
  --flat-dir /home/nq10083194/terraform-export-flat \
  --dry-run

# Run for real
python "TEF remediation/scripts/propagate_tf_env.py" \
  --flat-dir /home/nq10083194/terraform-export-flat
```

**All options**

| Flag | Default | Description |
|---|---|---|
| `--flat-dir PATH` | `/home/nq10083194/terraform-export-flat` | Parent of the `prod/` source folder. |
| `--dry-run` | off | Print planned writes and show up to 3 example substitutions per file without writing. |

**Output**
Creates `prod_dev-gke/` and `prod_test/` as siblings of `prod/`, each mirroring
the full folder structure of `prod/` with environment tokens substituted.
Prints a per-target file count and total substitution count.
Re-running overwrites existing files.

---

### 8. `export_bq_to_tf.py`

**Purpose**
Supplements `gcloud beta resource-config bulk-export` by querying the BigQuery API
directly and generating Terraform HCL for every dataset, table, and routine in a
project. Use this when bulk-export misses resources because they are not indexed in
Cloud Asset Inventory (CAI).

Output files use the same directory structure as `gcloud bulk-export`:

```
{exports_dir}/{env}/projects/{project_id}/BigQueryDataset/{dataset_id}.tf
{exports_dir}/{env}/projects/{project_id}/BigQueryTable/{table_id}.tf
{exports_dir}/{env}/projects/{project_id}/BigQueryRoutine/{routine_id}.tf
```

`organize_tf_export_flat.py` processes the combined output unchanged.

Default behaviour is **supplement mode**: existing `.tf` files are skipped so the
gcloud export is not overwritten. Use `--overwrite` to regenerate everything.

All generated table files include `deletion_protection = false`.

**IAM required**
- `roles/bigquery.metadataViewer` on the project (to list datasets, tables, routines)

**Run**
```bash
cd ~/remediation

# Supplement the existing gcloud bulk-export for prod (skips existing files)
python "TEF remediation/scripts/export_bq_to_tf.py" \
  --project tefde-gcp-fastoss-prod \
  --exports-dir /home/nq10083194/gcp-exports \
  --env prod

# Only a specific dataset
python "TEF remediation/scripts/export_bq_to_tf.py" \
  --project tefde-gcp-fastoss-prod \
  --exports-dir /home/nq10083194/gcp-exports \
  --env prod \
  --dataset pl_energy

# Dry run to preview what would be written
python "TEF remediation/scripts/export_bq_to_tf.py" \
  --project tefde-gcp-fastoss-prod \
  --exports-dir /home/nq10083194/gcp-exports \
  --env prod \
  --dry-run
```

After running, re-run `organize_tf_export_flat.py` as usual — it picks up the
newly generated files together with the existing gcloud output.

**All options**

| Flag | Default | Description |
|---|---|---|
| `--project ID` | _(required)_ | GCP project ID. |
| `--env NAME` | `prod` | Environment name used as the subdirectory under `--exports-dir`. |
| `--exports-dir PATH` | `/home/nq10083194/gcp-exports` | Parent of per-env export folders. |
| `--overwrite` | off | Overwrite `.tf` files that already exist (default: skip). |
| `--dataset DATASET_ID` | all | Only export this dataset. Repeatable. |
| `--dry-run` | off | Print planned writes without writing files. |

**Output**
Prints per-dataset counts of files written, skipped, and errors.
Table type (`TABLE`, `VIEW`, `MATERIALIZED_VIEW`, `EXTERNAL`) is shown for each written file.

---

### 9. `compare_bq_structure.py`

**Purpose**
Compares BigQuery table partitioning and clustering settings across GCP environments
(default: prod, test, dev-gke) and reports discrepancies. Designed to catch drift
after propagating Terraform exports from prod to lower environments.

For each table the script checks:
- `time_partitioning` (type, field, expiration_ms, require_partition_filter)
- `range_partitioning` (field, range start / end / interval)
- `clustering_fields` (sorted list of column names)

Two discrepancy classes are reported:
- **MISSING** — table exists in prod but is absent from one or more lower envs
- **DIFF** — table present in all envs but has different partitioning or clustering settings

Results are written to `devops_reports.bq_structure_drift` in `tefde-gcp-fastoss-dev`
(the same dataset used by all other reports). A companion view
`bq_structure_drift_report` (created by Terraform) provides a `run_number` field for
Looker Studio filtering.

**IAM required**
- `roles/bigquery.metadataViewer` on the prod, test, and dev-gke projects
- `roles/bigquery.dataEditor` on `devops_reports.bq_structure_drift` in `tefde-gcp-fastoss-dev`
- `roles/bigquery.dataEditor` on `devops_reports.executions` in `tefde-gcp-fastoss-dev` (execution logging)
- `roles/storage.objectAdmin` on the reports GCS bucket (reads the dataset→repo mapping file)
- `roles/secretmanager.secretAccessor` on the `gitlab-token` secret (clones repos for the mapping)

**Run**
```bash
cd ~/remediation

# Full report — all datasets, prod vs test vs dev-gke, write to BigQuery
python "TEF remediation/scripts/compare_bq_structure.py"

# Single dataset — faster, good for spot checks
python "TEF remediation/scripts/compare_bq_structure.py" \
  --dataset pl_energy

# Also export a CSV
python "TEF remediation/scripts/compare_bq_structure.py" \
  --output bq_structure_report.csv

# prod vs test only, skip BigQuery write
python "TEF remediation/scripts/compare_bq_structure.py" \
  --envs prod,test \
  --no-bq
```

**All options**

| Flag | Default | Description |
|---|---|---|
| `--envs LIST` | `prod,test,dev-gke` | Comma-separated environments. First env is the reference (source of truth for MISSING checks). |
| `--dataset DATASET_ID` | all | Only compare this dataset. Repeatable. |
| `--reporting-project ID` | `tefde-gcp-fastoss-dev` | Project holding `devops_reports`. |
| `--mapping-file PATH` | none | Path to a local `dataset_repo_map.json` (produced by `generate_dataset_mapping.py`). When provided, a `repository` column is added to every output row linking the dataset to its GitLab repo. |
| `--output PATH` | none | Also write results to a CSV file. |
| `--no-bq` | off | Skip BigQuery write; print to terminal and/or CSV only. |
| `--workers N` | `3` | Thread-pool size for parallel project fetching. |

**Output**
Terminal: summary counts (MISSING / DIFF), then a capped table of up to 50 rows.
BigQuery: rows appended to `devops_reports.bq_structure_drift` (partitioned by `checked_at`, clustered by `dataset_id`). Includes a `repository` column when `--mapping-file` is provided.
Each run also writes one row to `devops_reports.executions` (success or failure) so the run appears in the Jobs Runs Status dashboard.
Each run gets a unique `run_id` (e.g. `20260924T143012Z`) so historical data is preserved for trending.

**Looker Studio dashboard setup**

Connect to the `bq_structure_drift_report` view in project `tefde-gcp-fastoss-dev`,
dataset `devops_reports`.

Suggested charts:
1. **Scorecard** — count of rows where `discrepancy = 'MISSING'` and `run_number = 1`
2. **Scorecard** — count of rows where `discrepancy = 'DIFF'` and `run_number = 1`
3. **Table** — filter `run_number = 1`; columns: `repository`, `dataset_id`, `table_id`, `table_type`, `discrepancy`, `attribute`, `prod_value`, `test_value`, `dev_gke_value`
4. **Bar chart** — discrepancy count by `dataset_id` (latest run)
5. **Time-series line chart** — total discrepancy count per `run_date` (trend over time)
6. **Filter control** on `run_date` and `run_number`

> The `repository` column is populated automatically by the Cloud Run Job (which runs `generate_dataset_mapping.py` before each compare). When running the script locally with `--no-bq`, pass `--mapping-file dataset_repo_map.json` to populate it.

> "Enable date range parameters" must be **UNCHECKED** on this data source.
