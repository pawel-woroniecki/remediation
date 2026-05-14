# Git GCP Code Vs Environment Drift

This report compares one data product source snapshot against deployed BigQuery metadata and GCS artifacts to highlight drift between code and the selected environment.

## What It Produces

Each run writes a timestamped folder under `outputs/`, for example:

- `outputs/my_product_20260413T101500Z/`

Files:

- `report.md`
  Human-readable discrepancy summary
- `bigquery_findings.csv`
  BigQuery-only findings such as missing objects, schema drift, and definition mismatches
- `gcs_findings.csv`
  GCS artifact drift findings
- `inventory_snapshot.json`
  Full structured snapshot of source and deployed inventories

## How To Run

Branch-based source comparison:

```powershell
python .\reports\git_gcp_code_vs_environment_drift\generate_code_environment_drift_report.py `
  --project-name my_product `
  --repo-path C:\repos\fastossb\ndl_core\my_product
```

Common options:

```powershell
python .\reports\git_gcp_code_vs_environment_drift\generate_code_environment_drift_report.py `
  --project-name my_product `
  --repo-path C:\repos\fastossb\ndl_core\my_product `
  --git-ref production `
  --gcp-project tefde-gcp-fastoss-prod `
  --gcs-bucket fastoss-prod-composer-3
```

If `BQ_DATASET_NAMES` is not available in the product `.gitlab-ci.yml`, pass datasets explicitly:

```powershell
python .\reports\git_gcp_code_vs_environment_drift\generate_code_environment_drift_report.py `
  --project-name my_product `
  --repo-path C:\repos\fastossb\ndl_core\my_product `
  --datasets dataset_one dataset_two
```

Environment variables:

- `NEXUS_USER`
  Optional default for `--nexus-user`
- `NEXUS_PASSWORD`
  Optional default for `--nexus-password`

These variables are used only when the corresponding CLI arguments are not passed, and they matter only for `--source-mode nexus`.

## Prerequisites

- Python 3 available in PATH
- `git` available in PATH
- `gcloud` installed and authenticated
- BigQuery metadata access to the target project
- GCS read access to the target Composer bucket
- `curl.exe` available in PATH when using the default REST client setting

## Notes

- The script reads production-style settings from the product `.gitlab-ci.yml` when possible.
- By default it compares against the `production` Git ref.
- `--source-mode nexus` is also supported for comparing released Nexus artifacts instead of a Git branch snapshot.
