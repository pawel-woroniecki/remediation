# DevOps Reports

This repo contains small DevOps and platform reporting scripts plus a few utility tools.

## Structure

```
reports/
  bigquery_column_lookup/
  bigquery_orphan_datasets/
  git_source_dependency_lookup/
  bigquery_table_encryption/
  git_branches_gap/
  git_gcp_code_vs_environment_drift/
  git_top_contibutors/
tools/
  clone_all_groups_repo/
  confluence_sync/
  scan_networks/
outputs/
```

## Reports

- `git_gcp_code_vs_environment_drift`: compares one data product source snapshot against deployed BigQuery and GCS state.
  - Run:
    - `python ./reports/git_gcp_code_vs_environment_drift/generate_code_environment_drift_report.py --project-name <project_name> --repo-path <repo_path>`
- `bigquery_orphan_datasets`: scans prod BigQuery datasets and flags datasets not referenced by subgroup `BQ_DATASET_NAMES`.
  - Run:
    - `python ./reports/bigquery_orphan_datasets/unmatched_bq_datasets_report.py`
- `git_branches_gap`: compares `origin/master` and `origin/production` across cloned repos.
  - Run:
    - `./reports/git_branches_gap/production_master_gap_report.ps1`
- `git_top_contibutors`: subgroup-wide Git contributor ranking for the selected branch.
  - Run:
    - `./reports/git_top_contibutors/top_master_contributors_report.ps1`
- `bigquery_table_encryption`: inventories BigQuery table encryption posture and CMEK governance.
  - Run:
    - `./reports/bigquery_table_encryption/table_encryption_report.ps1`
- `bigquery_column_lookup`: finds matching columns across BigQuery projects and datasets.
  - Run:
    - `./reports/bigquery_column_lookup/column_lookup_report.ps1 -ColumnPattern customer_id`
- `git_source_dependency_lookup`: finds local Git/source-code references to table/view-like names and optionally columns.
  - Run:
    - `./reports/git_source_dependency_lookup/git_source_dependency_lookup_report.ps1 -TablePattern 'dataset\.table_or_view'`

### Table Encryption Report

The table encryption report scans BigQuery metadata and produces:
- an executive summary markdown report
- a table-level CSV with encryption posture and creation time
- a dataset-level CSV rollup

Default behavior:
- scans `tefde-gcp-fastoss-prod`
- excludes datasets whose names start with `_`
- classifies tables as `encrypted_by_thales`, `encrypted_by_other_kms`, or `not_cmek`
- marks governance as `compliant`, `policy_gap`, or `noncompliant`

Example:

```powershell
./reports/bigquery_table_encryption/table_encryption_report.ps1
```

## Tools

- `tools/clone_all_groups_repo/clone_fastoss_b.ps1`: clones or updates the `fastoss_b` group locally.
  - Run:
    - `./tools/clone_all_groups_repo/clone_fastoss_b.ps1`
- `tools/confluence_sync/sync_confluence.py`: read-only Confluence page sync into local `outputs/` files for offline analysis.
  - Run from the repo root:
    - `python ./tools/confluence_sync/sync_confluence.py --config ./tools/confluence_sync/config.example.json`
    - `python ./tools/confluence_sync/sync_confluence.py --base-url https://confluence.telefonica.de --space-key FASB --root-page-id 68673499 --bearer-token $env:CONFLUENCE_BEARER_TOKEN --output-dir ./outputs/confluence_sync/fasb --include-children --http-timeout-seconds 180 --max-retries 5 --retry-backoff-seconds 3 --continue-on-error`
  - Output:
    - synced pages as `page.json`, `metadata.json`, `page.html`, `page.txt`
    - run metadata in `manifest.json`
    - optional failures in `failed_pages.json`

## Supported Environment Variables

The current scripts support these environment variables:

- `GITLAB_TOKEN`
  Required by `tools/clone_all_groups_repo/clone_fastoss_b.ps1`
- `CONFLUENCE_BASE_URL`, `CONFLUENCE_SPACE_KEY`, `CONFLUENCE_ROOT_PAGE_ID`, `CONFLUENCE_USERNAME`, `CONFLUENCE_TOKEN`, `CONFLUENCE_BEARER_TOKEN`
  Supported by `tools/confluence_sync/sync_confluence.py`
- `NEXUS_USER`, `NEXUS_PASSWORD`
  Supported by `reports/git_gcp_code_vs_environment_drift/generate_code_environment_drift_report.py` for Nexus mode
- `GCLOUD_PATH`
  Supported by `reports/bigquery_orphan_datasets/unmatched_bq_datasets_report.py`

## Outputs

Reports write markdown, CSV, and JSON outputs into `outputs/` by default. This folder is intended for generated artifacts and is safe to clean.
