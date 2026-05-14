# BigQuery Orphan Datasets

This report scans all datasets in one BigQuery project, reads `BQ_DATASET_NAMES` from every locally cloned repo inside one subgroup (lilke ndl_core), and flags datasets that exist in BigQuery env but are not referenced by any subgroup project in gitlab-ci.yml files.

It is intended to answer questions like:

- which datasets have no matching GitLab CI reference
- which objects exist inside those unmatched datasets
- which repos currently declare `BQ_DATASET_NAMES`, and which do not

## Main Script

- [unmatched_bq_datasets_report.py]

## What It Produces

Each run writes a timestamped output folder under `outputs/`, for example:

- `outputs/ndl_core_unmatched_bq_datasets_20260326_001500/`

Files:

- `report.md`
  Dataset-level summary only
- `unmatched_datasets.csv`
  One row per unmatched dataset
- `unmatched_objects.csv`
  Object-level detail for unmatched datasets
- `dataset_errors.csv`
  Datasets whose metadata could not be queried cleanly
- `repo_dataset_references.csv`
  Repo-to-dataset mapping extracted from `.gitlab-ci.yml`
- `unmatched_datasets.json`
  Full structured output

## How To Run

```powershell
python C:\repos\fastossb\devops-reports\reports\bigquery_orphan_datasets\unmatched_bq_datasets_report.py `
  --project-id tefde-gcp-fastoss-prod `
  --workspace-root C:\repos\fastossb `
  --subgroup ndl_core `
  --git-ref production `
  --output-dir C:\repos\fastossb\devops-reports\outputs
```

Mandatory parameters:

- `--workspace-root`
  Parent folder that contains subgroup directories such as `C:\repos\fastossb\ndl_core`

Optional parameters:

- `--project-id`
  BigQuery project to scan. Default: `tefde-gcp-fastoss-prod`
- `--subgroup`
  Subgroup folder under `--workspace-root`. Default: `ndl_core`
- `--git-ref`
  Repo-side dataset matching branch/ref. Default: `production`
- `--output-dir`
  Root folder where the timestamped run folder is created. Default: `.\outputs`

Optional filters:

- `--dataset-include-regex`
- `--dataset-exclude-regex`
- `--git-ref`
  Repo-side dataset matching uses this Git branch/ref. Default branch: `production`

Environment variables:

- `GCLOUD_PATH`
  Optional override for the `gcloud` executable path. This is used only when `--gcloud-path` is not passed.

Default exclusion:

- datasets whose names start with `_` are excluded by default
- this avoids temporary or hidden datasets that often cannot be queried through `INFORMATION_SCHEMA`

## Matching Logic

The report:

1. lists datasets from the target BigQuery project
2. scans every local Git repo under the selected subgroup
3. reads `BQ_DATASET_NAMES` from each repo `.gitlab-ci.yml` at the selected Git ref
4. splits that variable by comma into concrete dataset names
5. marks a BigQuery dataset as orphaned if no subgroup repo references it

## Notes

- Matching is based only on `BQ_DATASET_NAMES` in `.gitlab-ci.yml`
- Hidden/system datasets can exist in BigQuery but reject `INFORMATION_SCHEMA` queries; those are still listed and recorded in `dataset_errors.csv`
- `report.md` intentionally stays compact and dataset-focused; object-level detail goes into CSV/JSON outputs
