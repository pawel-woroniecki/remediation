# Developer Guide — `unmatched_bq_datasets_report.py`

This document explains the internal design of the orphan datasets script for
developers who need to maintain, extend, or debug it.
For operational use (parameters, examples, outputs) see [README.md](README.md).

---

## Purpose

The script identifies BigQuery datasets in a GCP project that are **not referenced
by any GitLab repository** in a given subgroup. A dataset is considered "managed"
if at least one repo declares it in the `BQ_DATASET_NAMES` CI variable on the
selected Git branch. Any dataset not found in that reference set is flagged as an
orphan — potentially a leftover from a decommissioned service or a manually
created dataset outside the IaC process.

---

## High-Level Flow

```
GCP ADC token
   │
   ├─► list_datasets()              ← BQ REST API — all datasets in the project
   │        │
   │        └─ filter by include/exclude regex
   │
   ├─► collect_repo_dataset_references()
   │        │
   │        ├─ for each repo in subgroup:
   │        │     resolve_branch_ref()            ← git show-ref
   │        │     read_file_from_git_ref()         ← git show ref:.gitlab-ci.yml
   │        │     load_gitlab_variables_from_text() ← custom YAML parser
   │        │     parse_dataset_names()            ← split BQ_DATASET_NAMES by comma
   │        └─ returns: dataset_to_repos dict
   │
   ├─► for each unmatched dataset:
   │     fetch_dataset_objects()    ← BQ INFORMATION_SCHEMA.TABLES + ROUTINES
   │
   ├─► write outputs: markdown, 4 CSVs, JSON
   ├─► upload_to_gcs()
   └─► write_to_bigquery()         ← orphan_dataset_objects, orphan_datasets, executions
```

---

## Key Functions

### `list_datasets(token, project_id)`

Calls the BQ REST API directly (`/bigquery/v2/projects/{id}/datasets?all=true`)
with pagination via `nextPageToken`. Using the REST API instead of the Python SDK
avoids an extra dependency and allows direct token injection.
Returns all dataset IDs as a sorted, deduplicated list.

### `collect_repo_dataset_references(subgroup_root, branch_name)`

Walks the local subgroup directory for Git repos. For each repo:
1. `resolve_branch_ref()` — tries `origin/<branch>` first, then local `<branch>`;
   returns whichever ref exists so the report reads the correct branch without
   requiring a local checkout.
2. `read_file_from_git_ref()` — reads `.gitlab-ci.yml` directly from the git
   object store (`git show ref:path`) without touching the working tree.
3. `load_gitlab_variables_from_text()` — parses the CI file for dataset names
   (see CI Parsing section below).

Returns two values: a list of `RepoDatasetReference` dataclasses, and a
`dataset_to_repos` dict mapping each dataset name to the list of repos that
claim it. A dataset is considered managed as soon as it appears in **any** repo.

### `fetch_dataset_objects(token, project_id, dataset)`

Queries `INFORMATION_SCHEMA.TABLES` and `INFORMATION_SCHEMA.ROUTINES` for the
given dataset via `bigquery_query()`. Tables and routines are queried
independently so a partial failure (e.g. permission denied for routines) still
returns the table-level results. Errors are collected and surfaced in the report
rather than aborting the run.

### `bigquery_query(token, project_id, sql)`

Runs a SQL query against the BQ REST API (`/queries` endpoint). Key behaviours:
- Checks `jobComplete` in the response and raises immediately if the query timed out.
- Paginates through all result pages using `pageToken` + `jobId` so large
  INFORMATION_SCHEMA results are fully consumed.
- Returns rows as `list[dict[str, Any]]` with field names from the response schema.

---

## CI File Parsing

The script reads dataset names from `.gitlab-ci.yml` without a full YAML parser
to avoid the PyYAML dependency in the Docker image.

### `extract_yaml_like_block(text, block_name, indent)`

Regex-based: matches `<block_name>:` at the given indent level and captures all
following lines that are indented by at least `indent + 2` spaces.

### `load_gitlab_variables_from_text(text)`

Two-pass merge:
1. Reads the top-level `variables:` block (indent 0) to get global CI variables.
2. For each of `deploy_to_prod_bq`, `deploy_to_prod_dbt`, `deploy_to_prod_python`,
   reads the job's nested `variables:` block (indent 2) and merges it on top.

This handles repos that define `BQ_DATASET_NAMES` at job level (overriding a
global value) while also covering repos that define it globally only.

### `parse_dataset_names(raw_value)`

Splits the `BQ_DATASET_NAMES` string value on commas and strips whitespace.
Returns an empty list when the variable is absent or empty.

---

## BigQuery Tables Written

Three tables are written in this order (objects → datasets → executions):

| Table | Rows | Key columns |
|---|---|---|
| `orphan_dataset_objects` | One per object in an orphaned dataset | `dataset_name`, `object_type`, `object_name` |
| `orphan_datasets` | One per orphaned dataset | `dataset_name`, `table_count`, `risk_score` |
| `executions` | One per run | `report_type = 'orphan_datasets'`, `status`, `duration_seconds` |

**Risk score**: `2` for datasets with at least one object, `1` for empty datasets.
Empty datasets carry lower risk because they have no data but still represent
governance clutter.

---

## GCP Authentication

`gcp_access_token()` uses Application Default Credentials (ADC) with the
`cloud-platform` scope. In Cloud Run the container's service account provides
the credential automatically. Locally, run `gcloud auth application-default login`.

The token is used directly in HTTP `Authorization: Bearer` headers for REST API
calls. The BigQuery Python SDK (`bigquery.Client`) is used only for streaming
inserts and the idempotency check query.

---

## Idempotency Guard

`execution_id_exists()` queries `executions` for the current `EXECUTION_ID`
within the last 2 days. If found, BQ writes are skipped. This prevents duplicate
rows from Cloud Run retries where the job re-executes after a transient failure
that happened after GCS upload but before BQ writes.

---

## Error Handling

- Per-dataset metadata errors (INFORMATION_SCHEMA failures) are collected in
  `dataset_errors` and written to `dataset_errors.csv`. They do not abort the run.
- A top-level `try/except` in `main()` writes `status = "failed"` to `executions`
  and re-raises. The Cloud Run Job then exits non-zero and is marked failed in GCP.

---

## Extending the Script

**Add a new managed-reference source** (e.g. Terraform files alongside `.gitlab-ci.yml`):
1. Add a new function analogous to `read_file_from_git_ref` / `load_gitlab_variables_from_text`.
2. Merge the results into `dataset_to_repos` inside `collect_repo_dataset_references`.

**Change the risk scoring**:
Edit `risk_score` in the `write_to_bigquery` call for `orphan_datasets` (around line 627).
Current logic: 2 if non-empty, 1 if empty.

---

## Local Development

```bash
export EXECUTION_ID=local-test-001
export TRIGGERED_BY=developer

python unmatched_bq_datasets_report.py \
  --project-id tefde-gcp-fastoss-prod \
  --workspace-root /path/to/cloned/repos \
  --subgroup ndl_core \
  --git-ref production \
  --gcp-project tefde-gcp-fastoss-dev \
  --reporting-project tefde-gcp-fastoss-dev \
  --gcs-bucket to-be-added-later \
  --output-dir /tmp/orphan-test
```

The `--gcs-bucket to-be-added-later` value will raise a `ValueError` before GCS
upload, leaving local CSV and JSON output intact for inspection. To skip GCS and
BQ, temporarily comment out `upload_to_gcs()` and `write_to_bigquery()` in `main()`.
