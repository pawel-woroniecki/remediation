# Developer Guide — `generate_code_environment_drift_report.py`

This document explains the internal design of the environment drift script for
developers who need to maintain, extend, or debug it.
For operational use (parameters, examples, outputs) see [README (1).md](<README (1).md>).

---

## Purpose

The script compares **what the Git source says should exist in GCP** against
**what actually exists in GCP right now**. It covers two resource types:

- **BigQuery** — tables, views, materialized views, routines per dataset
- **GCS** — DAG files deployed to Cloud Composer buckets

Any difference between the source and the live environment is a drift finding.
This is distinct from the branch drift scripts, which compare branches with
each other; this script compares code to the live environment.

---

## High-Level Flow

```
Git (source of truth)
   │
   ├─ build_source_bq_inventory()    ← clone repo, parse DDL / YAML files
   │       │
   │       └─ SourceBqObject dataclass per table/view/routine
   │
   └─ build_gcs_inventory()          ← list files from local GCS snapshot
           │
           └─ dict: path → hash

Live GCP (deployed state)
   │
   ├─ BQ API                         ← list datasets, tables, columns, views
   │
   └─ stage_gcs_snapshot()           ← gcloud storage cp → local temp dir
           │
           └─ build_gcs_inventory()

Comparison
   │
   ├─ compare_bigquery()  →  only_in_bq, only_in_source, type_mismatch, schema_mismatch
   └─ compare_gcs()       →  only_in_gcs, only_in_source, content_mismatch

   │
   └─ write findings → BQ env_drift_findings table + executions table + GCS CSV
```

---

## `SourceBqObject` Dataclass

Central data structure that accumulates everything known about one BQ object
from the source files before comparison against the live API.

| Field | Type | Meaning |
|---|---|---|
| `object_name` | `str` | Table / view / routine name |
| `dataset` | `str \| None` | BQ dataset it belongs to |
| `object_type` | `str` | `table`, `view`, `materialized_view`, `routine`, etc. |
| `columns` | `dict[str, str]` | Column name → canonical BQ type (from DDL parsing) |
| `sql_fragments` | `list[str]` | Raw SQL bodies collected from files |
| `alter_col_ops` | `list[tuple]` | `('add', col, type)` or `('drop', col)` from ALTER TABLE files, in file-processing order |
| `drop_cols` | `list[str]` | Columns removed by ALTER TABLE DROP statements |
| `rename_pairs` | `list[tuple[str,str]]` | `(old_name, new_name)` from RENAME COLUMN |
| `is_ctas` | `bool` | True when the DDL is CREATE TABLE AS SELECT (no explicit schema) |
| `multi_statement` | `bool` | True when the file contains multiple SQL statements |

A `SourceBqObject` for a complex table may be assembled from multiple files:
a base `CREATE TABLE` DDL, one or more `ALTER TABLE ADD COLUMN` migration files,
and a `DROP COLUMN` migration. The script replays these in order to reconstruct
the final expected schema.

---

## DDL Parsing

### `_CREATE_TABLE_BODY_RE`

Compiled regex (`re.IGNORECASE | re.DOTALL | re.MULTILINE`) that extracts the
column body from a `CREATE TABLE` DDL. The pattern:

```
CREATE [OR REPLACE] TABLE [IF NOT EXISTS] `project.dataset.table` (
  <body>
)  OPTIONS|PARTITION|CLUSTER|;
```

The body terminator matches `OPTIONS`, `PARTITION`, `CLUSTER`, or `;` at the
start of a line. This handles DDLs where the closing `)` is followed by `OPTIONS`
on the same line.

### `extract_columns_from_create_table(sql, target_name)`

Applies `_CREATE_TABLE_BODY_RE` to the SQL text and parses each line of the body:

- Strips trailing commas and inline comments (`-- ...`)
- Skips `PRIMARY KEY`, `FOREIGN KEY`, `UNIQUE`, `CHECK` constraints
- Skips `PARTITION BY`, `CLUSTER BY`, `ORDER BY` clauses (which can appear
  inside the body when the closing `)` is not on its own line)
- Matches column lines with `r"`?(?P<name>[\w\-]+)`?\s+(?P<dtype>[A-Z0-9_<>,]+)`
- Applies `.rstrip(",")` to the captured dtype to remove trailing commas left
  by inline comments (e.g. `col STRING, -- note`)
- Calls `canonical_bq_data_type()` to normalise type aliases

### `canonical_bq_data_type(dtype)`

Maps BQ type aliases to their canonical forms (e.g. `INTEGER` → `INT64`,
`VARCHAR` → `STRING`, `FLOAT` → `FLOAT64`). Handles parameterised types
(`NUMERIC(10,2)`) by taking only the base type before `<` or `(`.

---

## Source Inventory Building

### `build_source_bq_inventory()`

Walks the cloned repo directory for `*.sql` and `*.yml` files and accumulates
`SourceBqObject` instances. SQL files are categorised by their DDL keyword:

| SQL keyword | Object type |
|---|---|
| `CREATE TABLE` | `table` (or `external_table` if `OPTIONS(format=...)`) |
| `CREATE VIEW` / `CREATE OR REPLACE VIEW` | `view` |
| `CREATE MATERIALIZED VIEW` | `materialized_view` |
| `CREATE FUNCTION` / `CREATE PROCEDURE` | `routine` |
| `ALTER TABLE ... ADD COLUMN` | adds to existing object's `alter_col_ops` |
| `ALTER TABLE ... DROP COLUMN` | adds to existing object's `alter_col_ops` |
| `ALTER TABLE ... RENAME COLUMN` | adds to `rename_pairs` |

YAML files (dbt models) supply additional objects the SQL DDL doesn't cover.

### `build_gcs_inventory(gcs_snapshot_dir)`

Walks the locally staged GCS snapshot directory and builds a dict of
`{relative_path: sha256_hash}`. Binary files use byte-level hashing;
text files (`.sql`, `.yml`, `.py`, etc.) use content normalised to UTF-8.

---

## GCS Staging

### `stage_gcs_snapshot()`

Downloads the live GCS bucket to a local temp directory using
`gcloud storage cp -r gs://bucket/** /tmp/snapshot/`. The temp dir is cleaned
up after comparison. This approach avoids the need to stream-compare individual
files and allows content-hash comparison for all file types.

---

## Comparison Functions

### `compare_bigquery(source_inventory, bq_client)`

For each dataset/object pair:

| Condition | Finding type |
|---|---|
| In BQ but not in source (excluding `tmp_`, `merge_`) | `only_in_bq` |
| In source but not in BQ | `only_in_source` |
| Both exist, column counts match, types differ | `type_mismatch` |
| Both exist, column sets differ (added/removed columns) | `schema_mismatch` |

Column comparison uses `canonical_bq_data_type()` on both sides so that
`INTEGER` (source) matches `INT64` (BQ API).

### `compare_gcs(source_files, gcs_files)`

Compares the source-side file inventory against the GCS snapshot:

| Condition | Finding type |
|---|---|
| In source but not in GCS | `only_in_source` |
| In GCS but not in source (excluding `tmp_` stems) | `only_in_gcs` |
| Both exist, hashes differ | `content_mismatch` |

---

## Suppressed Objects

Some objects are intentionally excluded from findings to prevent false positives:

| Pattern | Scope | Reason |
|---|---|---|
| `tmp_` prefix | BQ `only_in_bq`, GCS `only_in_gcs` | Transient dbt intermediate models left behind after a run |
| `merge_` prefix | BQ `only_in_bq` | Temporary merge tables created and dropped by the pipeline |

---

## Parallel Execution

Repos are processed concurrently using `ThreadPoolExecutor`. The concurrency
limit is controlled by the `ENV_DRIFT_MAX_PARALLEL` environment variable
(default: 5). Each worker runs the full source-build + GCS-stage + comparison
pipeline for one repo independently. BQ writes are serialised after all workers
complete.

---

## BigQuery Tables Written

| Table | Rows | Key columns |
|---|---|---|
| `env_drift_findings` | One per finding | `finding_type`, `object_name`, `dataset`, `detail` |
| `executions` | One per run | `report_type = 'env_drift'`, `status`, `duration_seconds` |

Findings are written before the executions record so a BQ insert failure for
findings is captured as `status = "failed"` rather than appearing successful.

---

## Error Handling

- Per-repo errors (git clone failure, BQ API permission denied) are caught and
  recorded as `finding_type = 'error'` rows, not as a script failure.
- A top-level `try/except` in `main()` writes `status = "failed"` to
  `executions` and re-raises.

---

## Common False Positives and Their Fixes

| False positive | Root cause | Fix applied |
|---|---|---|
| Column reported as `type_mismatch` after inline comment | Regex captured `TYPE,` with trailing comma | `.rstrip(",")` on captured dtype group (commit `32e6ffb`) |
| `PARTITION` / `CLUSTER` reported as missing columns | DDL body terminator fell back to OPTIONS `)`, pulling clause lines into column body | Skip guard for `PARTITION/CLUSTER/ORDER BY` lines (commit `61f7cea`) |
| `tmp_` tables in `only_in_bq` / `only_in_gcs` | Earlier fix skipped source inventory but not the GCP-side loops | Explicit skip in `compare_bigquery` and `compare_gcs` (commit `c3641b4`) |

---

## Local Development

```bash
export EXECUTION_ID=local-test-001
export TRIGGERED_BY=developer

python generate_code_environment_drift_report.py \
  --gcp-project tefde-gcp-fastoss-prod \
  --reporting-project tefde-gcp-fastoss-dev \
  --reports-gcs-bucket tefde-gcp-fastoss-dev-gcs-devops-reports \
  --target-env prod \
  --git-ref production
```

Requires `gcloud auth application-default login`. To skip GCS snapshot
download (slow), pass `--no-gcs-compare` if implemented, or comment out
`stage_gcs_snapshot()` and `compare_gcs()` calls in `main()` for a
BQ-only run.
