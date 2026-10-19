# D-S-01 Backup and Rollback Procedure

| Field | Value |
|---|---|
| Document ID | D-S-01 |
| Version | 2.6 |
| Status | Draft for review |
| Previous version | 2.5 |

## Change log v2.5 → v2.6

| # | Finding | Fix applied |
|---|---|---|
| F27 | Connections export (Section 3 Step 8) used a single API call — silently truncates when connection count exceeds the default page size | Replaced with paginated loop matching the variables and DAG export pattern |
| F28 | Section 2 Step 11 backup checklist did not include "Active state recorded before pausing" despite Step 1 being a required pre-pause action | Added checklist item as the first entry |
| F29 | Section 9 Step 5 corrected-rollback path missing empty-diff guard after `git revert` — `git commit` would fail silently if nothing was staged | Added the same guard used in Section 8 Step 3 |
| F30 | Section 9 Step 3 data-validation query hardcoded to `tefde-gcp-fastoss-prod.analytics.sales_data` — uses the wrong table if the incident involved a different table | Replaced with `${DATA_PROJECT_ID}.${DATASET}.${TABLE}` variables |

## Change log v2.4 → v2.5

| # | Finding | Fix applied |
|---|---|---|
| F19 | `${RECOVERY_BASE}` used in Section 2 Step 0 and Section 3 Step 0 before the variable block that defines it (old Step 2) | Moved "Define variables" to Step 0 in both sections; renumbered old Step 0 → Step 1 and old Step 1 → Step 2 |
| F20 | Watermarks query in Section 2 Step 4 uses `insert_date` placeholder with no reference to Appendix A | Added Appendix A note to Step 4, matching the note already present in Step 6 |
| F21 | Section 9 Step 5 `git revert` missing `-m 1` (fails silently on MR merge commits) | Added `-m 1` to the corrected-rollback revert command |
| F22 | Airflow variables export (Section 3 Step 8) used a single API call — silently truncates when variable count exceeds the default page size | Replaced with a paginated loop matching the DAG export pattern |
| F23 | Section 5 Step 3 references `${BRANCH}` which is only exported in Section 4 — undefined in an independent execution | Added `export BRANCH="production"` to Section 5 Step 1 variable block |
| F24 | Section 3 Step 6 copied all of `${COMPOSER_BUCKET}/data`, duplicating the `dbt/` folder already backed up in Step 5 | Changed to `gsutil rsync -x "^dbt/"` to exclude the dbt subdirectory |
| F25 | Storage layout diagram in Section 1 still showed `20261019_prod/` (old date-only format) | Updated to `20261019_0800_prod/` to match the `%Y%m%d_%H%M` format |
| F26 | `RETURNED` variable computed in both DAG pagination loops but never used — loop terminates on `TOTAL` and `OFFSET` only | Removed unused assignment from both loops |

## Change log v2.3 → v2.4

| # | Finding | Fix applied |
|---|---|---|
| F1 | SQL syntax error in control totals query — `COUNTIF(ROW_NUMBER() OVER ...)` is invalid in BigQuery | Replaced with a valid correlated subquery using `GROUP BY … HAVING` |
| F2 | Airflow connections export does not capture secrets (REST API masks passwords) | Added masking warning; added separate Secret Manager export/import steps |
| F3 | `bq mk --dataset` fails on retry if the dataset already exists | Made the command idempotent: check-then-create |
| F4 | `sed` substitution breaks on project names with hyphens (e.g. `tefde-gcp-fastoss-prod`) | Replaced with `python3` string substitution |
| F6 | Code rollback via forward merge may produce partial state if `production` already contains failed commits | Changed to `git revert <backup_tag>..HEAD` on a branch from current `production` HEAD |
| F7 | `bq cp --replace` described as "atomic at BigQuery level" — incorrect for large partitioned tables | Removed false claim; added stop-readers requirement and query-based atomic alternative |
| F8 | DDL from `INFORMATION_SCHEMA.TABLES.ddl` claimed to include column-level policy tags — it does not | Fixed claim; added Step 4b to restore policy tags separately via the BigQuery API |
| F9 | `active_dags.txt` Airflow API call hard-coded `limit=200` — silently truncates if more DAGs exist | Replaced with paginated loop that collects all active DAGs |
| F10 | `git revert` on a branch with MR merge commits fails without `-m 1` flag | Added `-m 1` to revert command; added empty-staged-diff guard before commit |
| F11 | Staging bucket `<staging-bucket>` used in Section 7 DAG restore but never defined as a variable | Added `STAGING_BUCKET` to Section 7 variable block; replaced all placeholder occurrences |
| F12 | Connections restore used `POST` which returns 409 Conflict for existing connections, silently failing | Changed to DELETE-then-POST pattern with HTTP status check and per-connection error reporting |
| F13 | `bq query --replace` (Option A) silently strips production table labels and description | Added metadata-restoration block after Option A that re-applies description and labels from staging |
| F14 | Airflow variables restore `POST` loop also silently fails on 409 Conflict | Changed to DELETE-then-POST with HTTP status check, same pattern as connections |
| F15 | BQ restore procedure defined `TABLE` as a single variable with no iteration guidance for multiple tables | Added per-table loop note and `gsutil ls` discovery command at Section 6 Step 0 |
| F16 | `business_key` / `insert_date` placeholder column names had no companion mapping | Added Appendix A: per-table column mapping template with instructions for composite keys and surrogate timestamps |
| F17 | `RECOVERY_POINT` used `date +%Y%m%d` — two runs on the same day overwrote each other silently | Changed to `date +%Y%m%d_%H%M` in all three variable blocks and updated all example values |
| F18 | Step 9 (verify backup files) presented as an integrity check — it only checks file presence | Added explicit warning that Step 9 is a presence check; Step 10 (external table) is the actual integrity check |

## Change log v2.2 → v2.3

| # | Area | Change |
|---|---|---|
| C1 | CI/CD rollback | Replaced `rollback_production_*` branch approach (rejected by pipeline rules) with an MR-into-`production` flow that works within current TDL branch and environment rules. |
| C2 | All commands | Defined one canonical recovery-point variable `RECOVERY_POINT` used in every backup and restore command. |
| C3 | RPO | Added explicit freeze-boundary recording: producers stopped, queues drained, watermarks recorded, no-mutation window confirmed. |
| C4 | ETL backup/restore | Removed unsupported `gcloud sql backups create/restore` commands for Composer metadata DB. |
| C5 | Metadata | Added `INFORMATION_SCHEMA.TABLES.ddl` path for executable BigQuery DDL. |
| C6 | Data validation | Added control totals: row count, null counts, min/max timestamps, distinct key count, duplicate count. |
| C7 | Partition validation | Capture expected partition inventory from BigQuery metadata before remediation. |
| C8 | DAG validation | Expanded beyond smoke test: skipped models, missing source relations, unchanged high-water marks, empty outputs. |
| C9 | Paused-state restore | Record active state before pausing; resume only the recorded set. |
| C10 | Restore default | Changed to stage-validate-promote pattern. |
| C11 | Permission errors | Removed ad-hoc IAM binding; added CCoE access-request reference. |
| C12 | Pipeline references | Replaced GitHub/Jenkins with TDL GitLab host and environment names. |

---

## Purpose

This document defines the standardised procedures for performing backup and rollback operations across data, code, and deployment layers within the TEF environment, ensuring that systems can be reliably restored in the event of failures or unintended changes during remediation activities.

The procedure is designed to:
- Restore the exact pre-remediation state using current TDL controls in case of failure
- Ensure a verifiable Recovery Point Objective (RPO ≈ 0) through a documented freeze boundary
- Provide executable, testable commands — not conceptual descriptions

Users of this document are expected to follow the prescribed sequence and use the canonical recovery-point structure defined in Section 1 for all commands.

---

## Scope

| Layer | Systems |
|---|---|
| Data | BigQuery datasets in GCP data projects (e.g. `tefde-gcp-fastoss-prod`) |
| ETL execution | Cloud Composer / Airflow, dbt runtime, GCS execution assets in ETL projects (e.g. `tefde-gcp-fastoss-prod-gke`) |
| Source code | GitLab repositories under `FastOSS_B / ndl_core` on `dot-portal.de.pri.o2.com/gitlab` |
| Pipelines | TDL GitLab CI/CD pipelines triggered from `production` branch and version tags |

**Not in scope:** Composer internal metadata database (Google-managed Cloud SQL — backup and restore of this instance via `gcloud sql backups` is not supported).

---

## Execution environment

All backup and restore commands must be executed from an approved execution environment only (VDI or secured bastion host with configured access to GCP and GitLab). Commands use example values; substitute real project IDs, bucket names, and dataset names before running.

**Preflight permission check — run before any procedure:**

```bash
# BigQuery read access
bq show --project_id=$DATA_PROJECT_ID $DATASET

# GCS write access
gsutil ls $BACKUP_BUCKET

# Composer access
gcloud composer environments describe $COMPOSER_ENV --location=$COMPOSER_REGION

# GitLab access
curl --silent --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://dot-portal.de.pri.o2.com/gitlab/api/v4/projects/$GITLAB_PROJECT_ID" \
  | jq '.id'
```

If any preflight check fails, **stop and raise an access request through the CCoE access-request procedure** before continuing. Do not attempt to grant permissions ad-hoc.

---

## Section 1 — Canonical recovery-point structure

Every command in this document uses a single `RECOVERY_POINT` variable. This ensures backup and restore commands are always compatible.

```bash
# Set once; use everywhere
export RECOVERY_POINT="${DATE}_${ENV}"      # e.g. 20261019_0800_prod
export BACKUP_BUCKET="gs://tef-backup-bucket"
export RECOVERY_BASE="${BACKUP_BUCKET}/${RECOVERY_POINT}"
```

### Storage layout

```
gs://tef-backup-bucket/
  20261019_0800_prod/
    bq/
      <dataset>/
        <table>/
          <table>_*.parquet          ← data export
          <table>_schema.json        ← bq show output
          <table>_ddl.sql            ← executable CREATE statement
          <table>_control_totals.json← row/null/min/max/key counts
          <table>_partitions.json    ← partition inventory
    composer/
      dags/                          ← DAG files
      plugins/                       ← plugins
      dbt_runtime/                   ← compiled dbt artefacts
      data/                          ← supporting GCS assets
      config/
        composer_config.json
        airflow_variables.json
        airflow_connections.json
        airflow_secret_refs.json     ← Secret Manager secret IDs per connection
      freeze_state/
        active_dags.txt              ← DAGs active before pause
        active_connectors.txt
        active_schedules.txt
        watermarks.json
    gitlab/
      pipeline_<id>.json
      artifacts_<id>.zip
    evidence/
      backup_validation.json
      restore_validation.json
```

All restore commands derive paths from `RECOVERY_BASE`. An operator can reconstruct any restore command from the `RECOVERY_POINT` value alone.

---

## Section 2 — GCP BigQuery backup procedure

### Objective

Perform a complete, consistent, and auditable backup of BigQuery datasets before remediation activities with RPO ≈ 0.

### RPO ≈ 0 — freeze-boundary requirements

RPO ≈ 0 is only valid when the following freeze conditions are **all** met and recorded before the first `bq extract` command runs:

1. All Airflow DAGs writing to the target datasets are paused and have no running task instances.
2. Kafka Connect BigQuery sink connectors are stopped and their consumer-group offsets are recorded.
3. BigQuery Streaming API producers are stopped and the streaming buffer is confirmed drained (buffer size = 0 in `INFORMATION_SCHEMA.STREAMING_TIMELINE`).
4. Talend jobs and cron-triggered integrations are disabled.
5. Final source watermarks (e.g. Kafka topic offsets, Talend last-run timestamps) and target high-water marks (e.g. `MAX(insert_date)` per table) are recorded and stored in `${RECOVERY_BASE}/composer/freeze_state/watermarks.json`.
6. No BigQuery mutations occur from freeze-start to backup completion.
7. All tables in scope are exported in the same freeze window (not across separate windows).

**Any export that does not meet all seven conditions must be discarded and re-run after stopping all data sources.**

### Prerequisites

- `gcloud` CLI authenticated to the data project
- `bq` and `gsutil` CLI available
- Permissions: BigQuery Data Viewer, Storage Object Creator
- Backup bucket created and accessible

### Step 0 — Define variables

```bash
export DATE=$(date +%Y%m%d_%H%M)    # includes hours+minutes — prevents same-day collision
export ENV="prod"
export RECOVERY_POINT="${DATE}_${ENV}"
export BACKUP_BUCKET="gs://tef-backup-bucket"
export RECOVERY_BASE="${BACKUP_BUCKET}/${RECOVERY_POINT}"

export DATA_PROJECT_ID="tefde-gcp-fastoss-prod"
export DATASET="analytics"
export TABLES=("sales_data" "customers" "transactions")
```

### Step 1 — Record active state before pausing

Before pausing anything, record what is currently active. This list is used at the end of restore to resume only what was running.

```bash
# List active Airflow DAGs — paginated to collect ALL active DAGs (not capped at 200)
OFFSET=0
LIMIT=100
> active_dags_raw.txt   # empty the file

while true; do
  RESULT=$(curl -s --user "$AIRFLOW_USER:$AIRFLOW_PASSWORD" \
    "https://<airflow-webserver>/api/v1/dags?is_paused=false&limit=${LIMIT}&offset=${OFFSET}")

  echo "$RESULT" | jq -r '.dags[].dag_id' >> active_dags_raw.txt

  TOTAL=$(echo "$RESULT"    | jq '.total_entries')
  OFFSET=$((OFFSET + LIMIT))
  [ "$OFFSET" -ge "$TOTAL" ] && break
done

# Convert to JSON array and store
jq -R . active_dags_raw.txt | jq -s '.' > active_dags.txt
echo "Recorded $(jq 'length' active_dags.txt) active DAGs"

gsutil cp active_dags.txt ${RECOVERY_BASE}/composer/freeze_state/active_dags.txt
```

Record Kafka Connect connectors, Talend job schedules, and any other active integrations in the same folder before stopping them.

### Step 2 — Pause all data producers

Pause in this order:

1. Airflow DAGs (all DAGs writing to the target dataset)
2. Kafka Connect BigQuery sink connectors
3. Talend scheduled jobs
4. Any cron-triggered integrations

After pausing, confirm no running task instances remain before proceeding.

### Step 3 — Confirm BigQuery streaming buffer is drained

Run for each table before exporting:

```bash
for TABLE in "${TABLES[@]}"; do
  bq query --use_legacy_sql=false \
    "SELECT SUM(estimated_rows) AS buffered_rows
     FROM \`${DATA_PROJECT_ID}.${DATASET}\`.INFORMATION_SCHEMA.STREAMING_TIMELINE
     WHERE table_name = '${TABLE}'"
done
```

**Expected:** `buffered_rows = 0` or `NULL` for all tables. If non-zero, wait and re-check before proceeding.

### Step 4 — Record watermarks (freeze boundary)

> **Note:** Replace `insert_date` with the actual business timestamp column for each table. See **Appendix A** for the per-table column mapping. Use the same column here as in Step 6 (control totals) so freeze-boundary and control-total watermarks are consistent.

```bash
for TABLE in "${TABLES[@]}"; do
  bq query --use_legacy_sql=false --format=json \
    "SELECT
       '${TABLE}' AS table_name,
       COUNT(*) AS row_count,
       MAX(insert_date) AS max_insert_date,
       MIN(insert_date) AS min_insert_date
     FROM \`${DATA_PROJECT_ID}.${DATASET}.${TABLE}\`" \
  > ${TABLE}_watermark.json
done

# Merge into one file
jq -s '.' *_watermark.json > watermarks.json
gsutil cp watermarks.json ${RECOVERY_BASE}/composer/freeze_state/watermarks.json
```

### Step 5 — Capture partition inventory

```bash
for TABLE in "${TABLES[@]}"; do
  bq query --use_legacy_sql=false --format=json \
    "SELECT partition_id, total_rows, total_logical_bytes
     FROM \`${DATA_PROJECT_ID}.${DATASET}\`.INFORMATION_SCHEMA.PARTITIONS
     WHERE table_name = '${TABLE}'
     ORDER BY partition_id" \
  > ${TABLE}_partitions.json
  gsutil cp ${TABLE}_partitions.json \
    ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/${TABLE}_partitions.json
done
```

### Step 6 — Capture control totals

> **Note:** Replace `business_key` and `insert_date` with the actual primary-key and timestamp column names for each table before running. Maintain a per-table mapping document alongside this procedure.

```bash
for TABLE in "${TABLES[@]}"; do
  bq query --use_legacy_sql=false --format=json \
    "SELECT
       COUNT(*) AS row_count,
       COUNT(DISTINCT business_key) AS distinct_keys,
       SUM(CASE WHEN business_key IS NULL THEN 1 ELSE 0 END) AS null_keys,
       MIN(insert_date) AS min_ts,
       MAX(insert_date) AS max_ts,
       (SELECT COUNTIF(cnt > 1)
        FROM (
          SELECT COUNT(*) AS cnt
          FROM \`${DATA_PROJECT_ID}.${DATASET}.${TABLE}\`
          GROUP BY business_key
        )
       ) AS duplicate_key_groups
     FROM \`${DATA_PROJECT_ID}.${DATASET}.${TABLE}\`" \
  > ${TABLE}_control_totals.json
  gsutil cp ${TABLE}_control_totals.json \
    ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/${TABLE}_control_totals.json
done
```

### Step 7 — Export data to GCS

```bash
for TABLE in "${TABLES[@]}"; do
  bq extract \
    --destination_format=PARQUET \
    ${DATA_PROJECT_ID}:${DATASET}.${TABLE} \
    ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/${TABLE}_*.parquet
done
```

### Step 8 — Export schema (descriptive) and generate executable DDL

```bash
for TABLE in "${TABLES[@]}"; do
  # Descriptive JSON (reference)
  bq show --format=prettyjson ${DATA_PROJECT_ID}:${DATASET}.${TABLE} \
    > ${TABLE}_schema.json
  gsutil cp ${TABLE}_schema.json \
    ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/${TABLE}_schema.json

  # Executable DDL — table definition including partitioning, clustering, options
  bq query --use_legacy_sql=false --format=csv \
    "SELECT ddl FROM \`${DATA_PROJECT_ID}.${DATASET}\`.INFORMATION_SCHEMA.TABLES
     WHERE table_name = '${TABLE}'" \
    | tail -n +2 > ${TABLE}_ddl.sql
  gsutil cp ${TABLE}_ddl.sql \
    ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/${TABLE}_ddl.sql
done
```

**Note:** `INFORMATION_SCHEMA.TABLES.ddl` returns a ready-to-execute `CREATE TABLE` or `CREATE VIEW` statement including partitioning, clustering, and options. **Column-level policy tags are not included in this DDL** — they must be restored separately after table creation (see Section 6, Step 4b).

### Step 9 — Verify backup file presence

> **This is a presence check only — it confirms files exist and are non-zero in size. It does not verify content integrity.** A Parquet file from a failed or partial `bq extract` job will still appear here with a non-zero size. Step 10 (external table validation) is the actual integrity check; do not mark the backup complete based on Step 9 alone.

```bash
for TABLE in "${TABLES[@]}"; do
  echo "=== $TABLE ==="
  gsutil ls ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/
  gsutil du -h ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/
done
```

Expected: at least one `.parquet` file per table, non-zero size, plus `_schema.json`, `_ddl.sql`, `_control_totals.json`, `_partitions.json`.

### Step 10 — Validate backup with external table

```bash
bq show ${DATA_PROJECT_ID}:remediation_validation > /dev/null 2>&1 \
  || bq mk --dataset ${DATA_PROJECT_ID}:remediation_validation

for TABLE in "${TABLES[@]}"; do
  bq query --use_legacy_sql=false "
    CREATE OR REPLACE EXTERNAL TABLE \`${DATA_PROJECT_ID}.remediation_validation.${TABLE}_ext\`
    OPTIONS (
      format = 'PARQUET',
      uris = ['${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/${TABLE}_*.parquet']
    );"

  bq query --use_legacy_sql=false \
    "SELECT COUNT(*) AS ext_row_count
     FROM \`${DATA_PROJECT_ID}.remediation_validation.${TABLE}_ext\`"
done
```

Compare `ext_row_count` against the control totals captured in Step 6. They must match exactly.

### Step 11 — Backup success checklist

- [ ] Active DAG list recorded in `freeze_state/` before pausing
- [ ] All data producers paused before export
- [ ] Streaming buffer confirmed at zero
- [ ] Watermarks recorded in `freeze_state/watermarks.json`
- [ ] Partition inventory captured per table
- [ ] Control totals (row count, distinct keys, min/max timestamps) recorded
- [ ] Parquet export files present and non-zero for all tables
- [ ] Executable DDL (`.sql`) generated and stored
- [ ] External table validation: row counts match control totals
- [ ] All files stored under `${RECOVERY_BASE}/bq/`

---

## Section 3 — GCP ETL project backup procedure (Composer + Airflow + dbt)

### Objective

Perform a consistent backup of the ETL execution layer. This section covers DAGs, plugins, dbt runtime artefacts, and supporting GCS objects.

**Not covered:** Composer internal metadata database (Google-managed Cloud SQL). Backup and restore of this instance via `gcloud sql backups` is not supported. The only durable ETL state is the GCS assets and the Git repository.

### Step 0 — Define variables

```bash
export DATE=$(date +%Y%m%d_%H%M)    # includes hours+minutes — prevents same-day collision
export ENV="prod"
export RECOVERY_POINT="${DATE}_${ENV}"
export BACKUP_BUCKET="gs://tef-backup-bucket"
export RECOVERY_BASE="${BACKUP_BUCKET}/${RECOVERY_POINT}"
export COMPOSER_BUCKET="gs://fastoss-prod-composer-3"
export COMPOSER_ENV="<composer-environment-name>"
export COMPOSER_REGION="europe-west3"
export ETL_PROJECT_ID="tefde-gcp-fastoss-prod-gke"
```

### Step 1 — Record active state before pausing

**Do this before pausing anything.** You will resume only this recorded set after restore.

```bash
# Active DAGs — paginated to capture ALL active DAGs regardless of count
OFFSET=0
LIMIT=100
> active_dags_raw.txt

while true; do
  RESULT=$(curl -s --user "$AIRFLOW_USER:$AIRFLOW_PASSWORD" \
    "https://<airflow-webserver>/api/v1/dags?is_paused=false&limit=${LIMIT}&offset=${OFFSET}")

  echo "$RESULT" | jq -r '.dags[].dag_id' >> active_dags_raw.txt

  TOTAL=$(echo "$RESULT"    | jq '.total_entries')
  OFFSET=$((OFFSET + LIMIT))
  [ "$OFFSET" -ge "$TOTAL" ] && break
done

jq -R . active_dags_raw.txt | jq -s '.' > active_dags.txt
echo "Recorded $(jq 'length' active_dags.txt) active DAGs"
gsutil cp active_dags.txt ${RECOVERY_BASE}/composer/freeze_state/active_dags.txt

# Active Kafka Connect connectors
curl -s https://<kafka-connect-host>/connectors \
  | jq '.' > active_connectors.txt
gsutil cp active_connectors.txt \
  ${RECOVERY_BASE}/composer/freeze_state/active_connectors.txt

# Talend and cron schedule inventory — capture manually if no API available
echo "Capture active Talend schedules and cron jobs manually" \
  > active_schedules.txt
gsutil cp active_schedules.txt \
  ${RECOVERY_BASE}/composer/freeze_state/active_schedules.txt
```

### Step 2 — Pause pipelines

Pause in this order:
1. All Airflow DAGs
2. Kafka Connect connectors
3. Talend scheduled jobs
4. Cron-triggered integrations

Confirm no running task instances before proceeding.

### Step 3 — Back up DAGs

```bash
gsutil -m cp -r ${COMPOSER_BUCKET}/dags \
  ${RECOVERY_BASE}/composer/dags/

# Validate
gsutil ls ${RECOVERY_BASE}/composer/dags/
```

### Step 4 — Back up plugins

```bash
gsutil -m cp -r ${COMPOSER_BUCKET}/plugins \
  ${RECOVERY_BASE}/composer/plugins/

gsutil ls ${RECOVERY_BASE}/composer/plugins/
```

### Step 5 — Back up dbt runtime artefacts

```bash
gsutil -m cp -r ${COMPOSER_BUCKET}/data/dbt \
  ${RECOVERY_BASE}/composer/dbt_runtime/

gsutil ls ${RECOVERY_BASE}/composer/dbt_runtime/
```

This includes compiled models, runtime manifests, environment-resolved variables, and generated execution artefacts. The Git repository alone is not sufficient — the runtime state may differ due to CI/CD variable injection.

### Step 6 — Back up additional Composer data assets

```bash
# Back up supporting data assets — excludes dbt/ (backed up separately in Step 5)
gsutil -m rsync -r -x "^dbt/" \
  ${COMPOSER_BUCKET}/data \
  ${RECOVERY_BASE}/composer/data/
```

### Step 7 — Export Composer environment configuration

```bash
gcloud composer environments describe ${COMPOSER_ENV} \
  --location ${COMPOSER_REGION} \
  --project ${ETL_PROJECT_ID} \
  > composer_config.json

gsutil cp composer_config.json \
  ${RECOVERY_BASE}/composer/config/composer_config.json
```

### Step 8 — Export Airflow variables and connections

> **Warning — secrets are masked in the connections export.**
> The Airflow REST API returns connections with all password and secret fields replaced by `***`. The connections JSON is useful for structure (host, port, schema, connection type) but **does not contain credentials**. Connection secrets must be backed up separately from Secret Manager (Step 8b below).

```bash
# Variables — paginated to collect ALL variables (Airflow API enforces a page size)
OFFSET=0
LIMIT=100
> variables_raw.txt

while true; do
  RESULT=$(curl -s --user "$AIRFLOW_USER:$AIRFLOW_PASSWORD" \
    "https://<airflow-webserver>/api/v1/variables?limit=${LIMIT}&offset=${OFFSET}")

  echo "$RESULT" | jq -c '.variables[]' >> variables_raw.txt

  TOTAL=$(echo "$RESULT" | jq '.total_entries')
  OFFSET=$((OFFSET + LIMIT))
  [ "$OFFSET" -ge "$TOTAL" ] && break
done

# Wrap in a top-level "variables" array — matches the format expected by the restore step
jq -s '{"variables": .}' variables_raw.txt > airflow_variables.json
echo "Exported $(jq '.variables | length' airflow_variables.json) variables"

gsutil cp airflow_variables.json \
  ${RECOVERY_BASE}/composer/config/airflow_variables.json

# Connections structure — paginated to collect ALL connections (passwords masked — back up secrets separately in Step 8b)
OFFSET=0
LIMIT=100
> connections_raw.txt

while true; do
  RESULT=$(curl -s --user "$AIRFLOW_USER:$AIRFLOW_PASSWORD" \
    "https://<airflow-webserver>/api/v1/connections?limit=${LIMIT}&offset=${OFFSET}")

  echo "$RESULT" | jq -c '.connections[]' >> connections_raw.txt

  TOTAL=$(echo "$RESULT" | jq '.total_entries')
  OFFSET=$((OFFSET + LIMIT))
  [ "$OFFSET" -ge "$TOTAL" ] && break
done

# Wrap in a top-level "connections" array — matches the format expected by the restore step
jq -s '{"connections": .}' connections_raw.txt > airflow_connections.json
echo "Exported $(jq '.connections | length' airflow_connections.json) connections"

gsutil cp airflow_connections.json \
  ${RECOVERY_BASE}/composer/config/airflow_connections.json
```

### Step 8b — Export connection secret references from Secret Manager

For each Airflow connection that uses a Secret Manager secret, record the secret resource name. This is the only way to restore credentials after a full rebuild.

```bash
# List all Secret Manager secrets in the ETL project whose name matches the
# Airflow backend naming pattern: "airflow-connections-<conn_id>"
gcloud secrets list \
  --project ${ETL_PROJECT_ID} \
  --filter="name~airflow-connections" \
  --format="json" \
  > airflow_secret_refs.json

gsutil cp airflow_secret_refs.json \
  ${RECOVERY_BASE}/composer/config/airflow_secret_refs.json

echo "Recorded $(jq 'length' airflow_secret_refs.json) connection secrets"
```

Verify that the count of secret references matches the count of connections with masked passwords in `airflow_connections.json`.

### ETL backup checklist

- [ ] Active DAG list collected via paginated loop (not hard-capped at 200)
- [ ] Active connector and schedule inventory recorded in `freeze_state/` **before** pausing
- [ ] All pipelines paused with no running task instances
- [ ] DAG files copied to `${RECOVERY_BASE}/composer/dags/`
- [ ] Plugins copied to `${RECOVERY_BASE}/composer/plugins/`
- [ ] dbt runtime artefacts copied to `${RECOVERY_BASE}/composer/dbt_runtime/`
- [ ] Composer config JSON exported
- [ ] Airflow variables exported
- [ ] Airflow connections structure exported (note: passwords masked)
- [ ] Connection secret references exported from Secret Manager
- [ ] No missing or zero-size files

---

## Section 4 — Code backup procedure (GitLab)

### Principles

- Git is the source of truth for code; GCS runtime is the source of truth for execution state.
- Backups must be immutable (tags), not only branches.
- Rollback must be reproducible via the standard CI/CD path.

### Step 0 — Define variables

```bash
export REPO_URL="https://dot-portal.de.pri.o2.com/gitlab/fastoss_b/ndl_core/<repo-name>.git"
export BRANCH="production"
export DATE=$(date +%Y%m%d_%H%M)    # includes hours+minutes — prevents same-day collision
export ENV="prod"
export RECOVERY_POINT="${DATE}_${ENV}"
export BACKUP_TAG="backup_${RECOVERY_POINT}"
```

### Step 1 — Clone / update repository

```bash
git clone $REPO_URL
cd <repo-name>
git checkout $BRANCH
git pull origin $BRANCH

# Validate
git status   # expect: nothing to commit, working tree clean
git log -1   # record commit SHA
```

### Step 2 — Create immutable backup tag

```bash
git tag $BACKUP_TAG
git push origin $BACKUP_TAG

# Validate
git ls-remote --tags origin | grep $BACKUP_TAG
```

The tag must exist remotely before the backup is considered complete.

### Step 3 — Record backup tag and commit SHA

```bash
echo "{\"backup_tag\": \"${BACKUP_TAG}\", \"commit_sha\": \"$(git rev-parse HEAD)\", \"branch\": \"${BRANCH}\", \"recovery_point\": \"${RECOVERY_POINT}\"}" \
  > git_backup_record.json
gsutil cp git_backup_record.json \
  ${RECOVERY_BASE}/gitlab/git_backup_record.json
```

### Code backup checklist

- [ ] `production` branch is up to date
- [ ] Backup tag created and pushed to origin
- [ ] Commit SHA recorded in `${RECOVERY_BASE}/gitlab/git_backup_record.json`

---

## Section 5 — CI/CD backup procedure (GitLab)

### Step 1 — Identify latest successful pipeline

Open the TDL GitLab project at:
`https://dot-portal.de.pri.o2.com/gitlab/fastoss_b/ndl_core/<repo-name>`

Go to **CI/CD → Pipelines**, filter by **Status = passed**, and note:
- Pipeline ID
- Commit SHA
- Branch / tag

Or via API:

```bash
export GITLAB_HOST="https://dot-portal.de.pri.o2.com/gitlab"
export GITLAB_TOKEN="<your-personal-access-token>"
export GITLAB_PROJECT_ID="<project-id>"    # numeric ID from project Settings
export BRANCH="production"

curl --silent --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "${GITLAB_HOST}/api/v4/projects/${GITLAB_PROJECT_ID}/pipelines?status=success&per_page=1" \
  | jq '.[0]'
```

### Step 2 — Save pipeline metadata

```bash
PIPELINE_ID=<id-from-step-1>

curl --silent --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "${GITLAB_HOST}/api/v4/projects/${GITLAB_PROJECT_ID}/pipelines/${PIPELINE_ID}" \
  > pipeline_${PIPELINE_ID}.json

gsutil cp pipeline_${PIPELINE_ID}.json \
  ${RECOVERY_BASE}/gitlab/pipeline_${PIPELINE_ID}.json
```

### Step 3 — Download and store pipeline artefacts

```bash
JOB_NAME="deploy-production"   # replace with actual job name

curl --silent --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "${GITLAB_HOST}/api/v4/projects/${GITLAB_PROJECT_ID}/jobs/artifacts/${BRANCH}/download?job=${JOB_NAME}" \
  --output artifacts_${PIPELINE_ID}.zip

gsutil cp artifacts_${PIPELINE_ID}.zip \
  ${RECOVERY_BASE}/gitlab/artifacts_${PIPELINE_ID}.zip
```

### CI/CD backup checklist

- [ ] Pipeline ID and commit SHA recorded
- [ ] Pipeline metadata JSON stored under `${RECOVERY_BASE}/gitlab/`
- [ ] Artefacts ZIP stored under `${RECOVERY_BASE}/gitlab/`

---

## Section 6 — GCP BigQuery restore procedure

### Prerequisites

The following must exist under `${RECOVERY_BASE}/bq/`:
- Parquet data files
- `_ddl.sql` executable DDL per table
- `_control_totals.json` per table
- `_partitions.json` per table

Permissions required: BigQuery Data Editor, GCS Object Viewer.

### Step 0 — Define recovery point

> **This procedure is per-table. Run Steps 0–11 for every table in the backup scope.**
> To list all tables that were backed up:
> ```bash
> gsutil ls ${RECOVERY_BASE}/bq/${DATASET}/
> ```
> Set `TABLE` to each table name in turn and execute Steps 1–11 before moving to the next.

```bash
export RECOVERY_POINT="20261019_0800_prod"     # the recovery point to restore FROM
export BACKUP_BUCKET="gs://tef-backup-bucket"
export RECOVERY_BASE="${BACKUP_BUCKET}/${RECOVERY_POINT}"
export DATA_PROJECT_ID="tefde-gcp-fastoss-prod"
export DATASET="analytics"

# Set TABLE to each table name in turn — repeat Steps 1-11 per table
export TABLE="sales_data"
```

### Step 1 — Confirm backup files exist

```bash
gsutil ls ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/
```

Expected: Parquet files, `_ddl.sql`, `_schema.json`, `_control_totals.json`, `_partitions.json`. If any are missing, do not proceed.

### Step 2 — Protect current table (pre-rollback snapshot)

```bash
bq cp \
  ${DATA_PROJECT_ID}:${DATASET}.${TABLE} \
  ${DATA_PROJECT_ID}:${DATASET}.${TABLE}_pre_rollback_${RECOVERY_POINT}

bq ls ${DATASET} | grep ${TABLE}
```

### Step 3 — Create staging dataset (idempotent)

```bash
# Create only if it does not already exist — safe to re-run on retry
bq show ${DATA_PROJECT_ID}:remediation_restore > /dev/null 2>&1 \
  || bq mk --dataset ${DATA_PROJECT_ID}:remediation_restore
```

### Step 4 — Create staging table from executable DDL

Download the DDL and adjust the table reference to point to the staging location.

> **Note:** The substitution uses `python3` to avoid `sed` pattern-matching issues with hyphens and dots in project names such as `tefde-gcp-fastoss-prod`.

```bash
gsutil cp \
  ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/${TABLE}_ddl.sql .

# Replace production table reference with staging reference
python3 -c "
import sys
src = open('${TABLE}_ddl.sql').read()
src = src.replace(
    '\`${DATA_PROJECT_ID}.${DATASET}.${TABLE}\`',
    '\`${DATA_PROJECT_ID}.remediation_restore.${TABLE}_stage\`'
)
open('${TABLE}_stage_ddl.sql', 'w').write(src)
"

bq query --use_legacy_sql=false < ${TABLE}_stage_ddl.sql
```

This creates the staging table with the correct partitioning, clustering, schema, and options from the executable DDL.

> **Column-level policy tags are NOT included in `INFORMATION_SCHEMA.TABLES.ddl`.** Policy tags (Data Catalog, column-level access control) must be restored separately in Step 4b after the table is created. Do not assume the staging table is fully secured until Step 4b completes.

### Step 4b — Restore column-level policy tags

Policy tags are defined in Data Catalog and applied via the BigQuery column schema. Retrieve the pre-backup schema JSON (which does contain policy tag references) and apply them:

```bash
gsutil cp \
  ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/${TABLE}_schema.json .

# Extract field-level policyTags from the schema JSON
# and apply to the staging table using the BigQuery API
python3 -c "
import json, subprocess

with open('${TABLE}_schema.json') as f:
    meta = json.load(f)

fields = meta.get('schema', {}).get('fields', [])
tagged = [f for f in fields if f.get('policyTags')]

if not tagged:
    print('No policy tags found in backup schema — skipping.')
else:
    print(f'Applying policy tags to {len(tagged)} column(s).')
    # Write the field list as a schema file for bq update
    with open('${TABLE}_schema_fields.json', 'w') as out:
        json.dump(fields, out)

    result = subprocess.run([
        'bq', 'update',
        '--schema', '${TABLE}_schema_fields.json',
        '${DATA_PROJECT_ID}:remediation_restore.${TABLE}_stage'
    ], capture_output=True, text=True)

    print(result.stdout)
    if result.returncode != 0:
        print('ERROR:', result.stderr)
        raise SystemExit(1)
"
```

Verify policy tags are present on the staging table:

```bash
bq show --format=prettyjson \
  ${DATA_PROJECT_ID}:remediation_restore.${TABLE}_stage \
  | jq '.schema.fields[] | select(.policyTags != null) | {name, policyTags}'
```

### Step 5 — Load data into staging table

```bash
bq load \
  --source_format=PARQUET \
  ${DATA_PROJECT_ID}:remediation_restore.${TABLE}_stage \
  ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/${TABLE}_*.parquet
```

### Step 6 — Validate staging table against control totals

Download the pre-backup control totals:

```bash
gsutil cp \
  ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/${TABLE}_control_totals.json .
```

Run the same control-total query against the staging table:

```bash
bq query --use_legacy_sql=false --format=json "
  SELECT
    COUNT(*) AS row_count,
    COUNT(DISTINCT business_key) AS distinct_keys,
    SUM(CASE WHEN business_key IS NULL THEN 1 ELSE 0 END) AS null_keys,
    MIN(insert_date) AS min_ts,
    MAX(insert_date) AS max_ts
  FROM \`${DATA_PROJECT_ID}.remediation_restore.${TABLE}_stage\`" \
> restored_control_totals.json
```

Compare automatically — no output means all values match:

```bash
diff \
  <(jq -S '.[0] | del(.duplicate_key_groups)' ${TABLE}_control_totals.json) \
  <(jq -S '.[0]' restored_control_totals.json)
```

If `diff` produces any output, the restore does not match the backup. Do not promote.

### Step 7 — Validate partition inventory

```bash
gsutil cp \
  ${RECOVERY_BASE}/bq/${DATASET}/${TABLE}/${TABLE}_partitions.json .

bq query --use_legacy_sql=false --format=json "
  SELECT partition_id, total_rows
  FROM \`${DATA_PROJECT_ID}.remediation_restore\`.INFORMATION_SCHEMA.PARTITIONS
  WHERE table_name = '${TABLE}_stage'
  ORDER BY partition_id" \
> restored_partitions.json

# Automated comparison
diff \
  <(jq -S '.' ${TABLE}_partitions.json) \
  <(jq -S '.' restored_partitions.json)
```

Missing or extra partitions are a blocker. Do not promote until `diff` shows no output.

### Step 8 — Validate metadata

```bash
bq show --format=prettyjson \
  ${DATA_PROJECT_ID}:remediation_restore.${TABLE}_stage
```

Confirm the following are present and correct:
- `timePartitioning` or `rangePartitioning`
- `clustering.fields`
- `schema.fields` (column names and types)
- `labels`
- `description`
- `policyTags` per column (restored in Step 4b)

### Step 9 — Promote staging table to production

> **Important:** Before running this command, confirm all readers of `${DATASET}.${TABLE}` are stopped (see Section 7 Step 0 — ETL restore). BigQuery `bq cp` for partitioned tables copies partition-by-partition and is **not a single atomic operation**. A concurrent read during the copy may see an inconsistent mixture of old and new partitions.
>
> **Alternative (preferred for large partitioned tables):** Use a BigQuery query job with `WRITE_TRUNCATE` disposition. A single query job is submitted as one atomic unit and no partial reads are possible against the destination while it runs:
>
> ```bash
> bq query --use_legacy_sql=false \
>   --destination_table=${DATA_PROJECT_ID}:${DATASET}.${TABLE} \
>   --replace \
>   "SELECT * FROM \`${DATA_PROJECT_ID}.remediation_restore.${TABLE}_stage\`"
> ```
>
> Use `bq cp` only when the table is small (< 1 partition) or all readers have been confirmed stopped.

Only promote after Steps 6, 7, and 8 all pass.

```bash
# Option A — query job (preferred, single atomic job)
bq query --use_legacy_sql=false \
  --destination_table=${DATA_PROJECT_ID}:${DATASET}.${TABLE} \
  --replace \
  "SELECT * FROM \`${DATA_PROJECT_ID}.remediation_restore.${TABLE}_stage\`"

# Option B — bq cp (only if all readers are stopped and table is unpartitioned or small)
# bq cp --replace \
#   ${DATA_PROJECT_ID}:remediation_restore.${TABLE}_stage \
#   ${DATA_PROJECT_ID}:${DATASET}.${TABLE}
```

> **Option A only: re-apply table metadata after promotion.**
> `bq query --replace` derives the schema from the query result and does not carry over labels or description from the destination table. Apply them from the staging table (which was created from the backup DDL and carries the original metadata):

```bash
# Only required after Option A — bq cp (Option B) preserves metadata automatically
STAGING_META=$(bq show --format=prettyjson \
  ${DATA_PROJECT_ID}:remediation_restore.${TABLE}_stage)

# Re-apply description
DESCRIPTION=$(echo "$STAGING_META" | jq -r '.description // empty')
[ -n "$DESCRIPTION" ] && bq update \
  --description "$DESCRIPTION" \
  ${DATA_PROJECT_ID}:${DATASET}.${TABLE}

# Re-apply labels (one bq update call per label)
echo "$STAGING_META" | jq -r '.labels // {} | to_entries[] | "\(.key)=\(.value)"' \
  | while read label; do
    bq update --set_label "$label" ${DATA_PROJECT_ID}:${DATASET}.${TABLE}
    echo "Applied label: $label"
  done

echo "Metadata restoration complete for ${TABLE}"
```

### Step 10 — Validate downstream compatibility

Run the production Airflow DAG or Composer job that reads this table. Do not use a local developer test.

```bash
# Trigger via Airflow API
curl -s --user "$AIRFLOW_USER:$AIRFLOW_PASSWORD" \
  -X POST "https://<airflow-webserver>/api/v1/dags/<dag-id>/dagRuns" \
  -H "Content-Type: application/json" \
  -d '{"conf": {}}'
```

Verify: no BigQuery errors, no missing tables, no missing permissions.

### Step 11 — Clean up staging

```bash
bq rm -f ${DATA_PROJECT_ID}:remediation_restore.${TABLE}_stage
# Remove pre-rollback copy only after full validation
bq rm -f ${DATA_PROJECT_ID}:${DATASET}.${TABLE}_pre_rollback_${RECOVERY_POINT}
```

### BigQuery restore checklist

- [ ] Backup files confirmed present under `${RECOVERY_BASE}/bq/`
- [ ] Current table copied as `_pre_rollback_` snapshot
- [ ] Staging dataset created (idempotent — safe to re-run)
- [ ] Staging table created from executable DDL (not manual JSON)
- [ ] Policy tags restored separately via BigQuery schema update (Step 4b)
- [ ] Data loaded into staging table
- [ ] Control totals `diff` produced no output
- [ ] Partition inventory `diff` produced no output
- [ ] Metadata (partitioning, clustering, labels, policy tags) verified
- [ ] All readers stopped before promotion (for partitioned tables)
- [ ] Staging promoted to production (query-job method preferred)
- [ ] Production DAG/pipeline validation passed
- [ ] Staging and pre-rollback copies cleaned up
- [ ] Evidence stored in `${RECOVERY_BASE}/evidence/`

---

## Section 7 — GCP ETL restore procedure (Composer / Airflow / dbt)

### Sequence requirement

ETL restore **must always follow** BigQuery restore. Starting ETL before data consistency is established causes failures or silent corruption.

### Step 0 — Stop pipelines

Before restoring:
- Pause all Airflow DAGs
- Stop Kafka Connect connectors
- Prevent new scheduled runs

### Step 1 — Define recovery point

```bash
export RECOVERY_POINT="20261019_0800_prod"
export BACKUP_BUCKET="gs://tef-backup-bucket"
export RECOVERY_BASE="${BACKUP_BUCKET}/${RECOVERY_POINT}"
export COMPOSER_BUCKET="gs://fastoss-prod-composer-3"
export STAGING_BUCKET="gs://tef-restore-staging"    # temporary staging bucket — must exist before restore
```

### Step 2 — Restore DAGs (stage-validate-promote)

```bash
# Stage to a temporary prefix first
gsutil -m cp -r \
  ${RECOVERY_BASE}/composer/dags/* \
  ${STAGING_BUCKET}/dags-stage/

# Validate staged files match backup manifest
gsutil ls ${STAGING_BUCKET}/dags-stage/ | sort > staged_dags.txt
gsutil ls ${RECOVERY_BASE}/composer/dags/ | sort > backup_dags.txt
diff backup_dags.txt staged_dags.txt    # expect: no differences

# Promote to Composer bucket (delete current, copy staged)
gsutil -m rm -r ${COMPOSER_BUCKET}/dags/*
gsutil -m cp -r ${STAGING_BUCKET}/dags-stage/* ${COMPOSER_BUCKET}/dags/

# Validate
gsutil ls ${COMPOSER_BUCKET}/dags/
```

### Step 3 — Restore plugins

```bash
gsutil -m rm -r ${COMPOSER_BUCKET}/plugins/*
gsutil -m cp -r \
  ${RECOVERY_BASE}/composer/plugins/* \
  ${COMPOSER_BUCKET}/plugins/

gsutil ls ${COMPOSER_BUCKET}/plugins/
```

### Step 4 — Restore dbt runtime artefacts

```bash
gsutil -m rm -r ${COMPOSER_BUCKET}/data/dbt/*
gsutil -m cp -r \
  ${RECOVERY_BASE}/composer/dbt_runtime/* \
  ${COMPOSER_BUCKET}/data/dbt/

gsutil ls ${COMPOSER_BUCKET}/data/dbt/
```

Verify dbt paths align with Airflow DAG configuration.

### Step 5 — Restore Airflow variables and connections

> **Restore order:** restore connection secrets from Secret Manager first (Step 5a), then import the connections structure. Importing connections without their secrets first will leave credentials empty.

#### Step 5a — Restore connection secrets

Verify that all connection secrets recorded in `airflow_secret_refs.json` still exist in Secret Manager with the expected values. If a secret was deleted or a new Composer environment was provisioned, re-create it:

```bash
gsutil cp ${RECOVERY_BASE}/composer/config/airflow_secret_refs.json .

# List the secrets and confirm they exist in the ETL project
jq -r '.[].name' airflow_secret_refs.json | while read SECRET_NAME; do
  gcloud secrets describe "${SECRET_NAME}" --project=${ETL_PROJECT_ID} \
    && echo "OK: ${SECRET_NAME}" \
    || echo "MISSING: ${SECRET_NAME} — must be re-created manually from a secure source"
done
```

Any `MISSING` secrets must be re-created from a secure credential source (e.g. the team password manager or the original infrastructure provisioning record) before the next step.

#### Step 5b — Restore variables and connections structure

```bash
gsutil cp ${RECOVERY_BASE}/composer/config/airflow_variables.json .
gsutil cp ${RECOVERY_BASE}/composer/config/airflow_connections.json .

# Restore variables — DELETE then POST to handle existing values (avoids 409 Conflict)
jq -c '.variables[]' airflow_variables.json | while read var; do
  KEY=$(echo $var | jq -r '.key')

  # Delete if exists (ignore 404)
  curl -s -o /dev/null \
    --user "$AIRFLOW_USER:$AIRFLOW_PASSWORD" \
    -X DELETE "https://<airflow-webserver>/api/v1/variables/${KEY}"

  # Create from backup
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
    --user "$AIRFLOW_USER:$AIRFLOW_PASSWORD" \
    -X POST "https://<airflow-webserver>/api/v1/variables" \
    -H "Content-Type: application/json" \
    -d "$var")
  [ "$HTTP" = "200" ] || [ "$HTTP" = "201" ] \
    && echo "Restored variable: ${KEY}" \
    || echo "ERROR restoring variable ${KEY} — HTTP ${HTTP}"
done

# Restore connections structure (passwords will be resolved from Secret Manager
# automatically by the Airflow secrets backend — do not attempt to inject
# masked *** values from the backup JSON)
#
# Strategy: DELETE the existing connection first (idempotent — 404 is acceptable),
# then POST the backup version. This avoids 409 Conflict on an in-place restore
# where connections already exist from a previous Airflow installation.
jq -c '.connections[]' airflow_connections.json | while read conn; do
  CONN_ID=$(echo "$conn" | jq -r '.connection_id')

  # Delete if exists (ignore 404)
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --user "$AIRFLOW_USER:$AIRFLOW_PASSWORD" \
    -X DELETE "https://<airflow-webserver>/api/v1/connections/${CONN_ID}")
  [ "$HTTP_STATUS" = "204" ] && echo "Deleted existing connection: ${CONN_ID}" \
    || echo "Connection not present, will create: ${CONN_ID}"

  # Create from backup
  RESULT=$(curl -s -o /dev/null -w "%{http_code}" \
    --user "$AIRFLOW_USER:$AIRFLOW_PASSWORD" \
    -X POST "https://<airflow-webserver>/api/v1/connections" \
    -H "Content-Type: application/json" \
    -d "$conn")
  [ "$RESULT" = "200" ] || [ "$RESULT" = "201" ] \
    && echo "Restored connection: ${CONN_ID}" \
    || echo "ERROR restoring connection ${CONN_ID} — HTTP ${RESULT}"
done
```

### Step 6 — Restore Composer environment configuration (if needed)

If the Composer environment was recreated due to disaster:

```bash
gsutil cp ${RECOVERY_BASE}/composer/config/composer_config.json .
gcloud composer environments create <env-name> \
  --location ${COMPOSER_REGION} \
  --project ${ETL_PROJECT_ID}
  # Apply relevant settings from composer_config.json manually
```

Note: `gcloud composer environments create` does not accept a config JSON directly. Apply settings (Python version, environment size, environment variables) from the config file manually.

### Step 7 — Sync with Git rollback tag

Ensure the Git rollback was applied (Section 8) before enabling DAGs.

```bash
git log -1   # verify commit SHA matches backup record
```

### Step 8 — Controlled pipeline reactivation — recorded set only

**Resume ONLY the DAGs and connectors that were active before the backup (recorded in `freeze_state/active_dags.txt`).** Do not resume everything.

```bash
gsutil cp ${RECOVERY_BASE}/composer/freeze_state/active_dags.txt .

while IFS= read -r DAG_ID; do
  echo "Unpausing: $DAG_ID"
  curl -s --user "$AIRFLOW_USER:$AIRFLOW_PASSWORD" \
    -X PATCH "https://<airflow-webserver>/api/v1/dags/${DAG_ID}" \
    -H "Content-Type: application/json" \
    -d '{"is_paused": false}'
done < <(jq -r '.[]' active_dags.txt)
```

Trigger each critical DAG manually and validate before enabling automatic scheduling.

### Step 9 — Validation

#### 9.1 DAG validation
- All expected DAGs visible in Airflow UI
- No import errors
- No syntax errors

#### 9.2 Execution validation (must use Composer/Airflow — not local dbt run)
- Tasks succeed
- dbt models execute via the Airflow DAG, not a local command
- No retries or failures

#### 9.3 Enhanced DAG validation (beyond smoke test)
For each restored DAG verify:
- No skipped models
- No missing source relations (`dbt source freshness` passes)
- High-water marks have advanced since the last successful run (not unchanged)
- Outputs are non-empty
- No data silently omitted (row count matches expectation from watermarks)

#### 9.4 Downstream validation
- Target BigQuery tables updated
- No missing partitions
- No data gaps vs. pre-backup watermarks

### ETL restore checklist

- [ ] BigQuery restore completed before ETL restore started
- [ ] All pipelines stopped before restoration
- [ ] DAGs staged, manifest validated, then promoted (not destructive-first)
- [ ] Plugins restored
- [ ] dbt runtime artefacts restored
- [ ] Connection secrets verified in Secret Manager before connections imported
- [ ] Airflow variables and connections structure restored
- [ ] Git rollback tag verified
- [ ] Only recorded-active DAGs re-enabled (not all DAGs)
- [ ] Kafka Connect connectors restarted (recorded set only)
- [ ] Enhanced DAG validation passed (no skipped models, high-water marks advanced)
- [ ] Evidence collected

---

## Section 8 — Code rollback procedure (Git)

### Rollback strategy

Rollback uses `git revert` to undo the failed remediation commits on a new branch, which is then merged into `production` via the standard MR approval flow. This approach:
- Works within current TDL pipeline rules (no force-push required)
- Produces an auditable revert commit in Git history
- Avoids merge-conflict risk that arises from merging the backup tag state into a `production` branch that already contains the failed commits

> **Why not branch from the backup tag?**
> Creating a branch from the backup tag and merging it into `production` produces a merge commit that blends the rollback state with whatever is currently on `production`. If `production` already contains the failed commits, the merge resolves differences rather than replacing them — the result may not match the backup state. `git revert` is the correct and explicit approach.

### Step 0 — Define variables

```bash
export RECOVERY_POINT="20261019_0800_prod"
export ROLLBACK_TAG="backup_${RECOVERY_POINT}"
export GITLAB_HOST="https://dot-portal.de.pri.o2.com/gitlab"
export REPO_URL="${GITLAB_HOST}/fastoss_b/ndl_core/<repo-name>.git"
```

### Step 1 — Fetch and verify rollback tag

```bash
git fetch --all --tags
git tag | grep $ROLLBACK_TAG
git show ${ROLLBACK_TAG} --stat
```

Confirm the tag commit matches the SHA recorded in `${RECOVERY_BASE}/gitlab/git_backup_record.json`.

```bash
EXPECTED_SHA=$(gsutil cat ${RECOVERY_BASE}/gitlab/git_backup_record.json | jq -r '.commit_sha')
ACTUAL_SHA=$(git rev-parse ${ROLLBACK_TAG})
echo "Expected: $EXPECTED_SHA"
echo "Actual:   $ACTUAL_SHA"
[ "$EXPECTED_SHA" = "$ACTUAL_SHA" ] && echo "SHA match — OK" || echo "SHA MISMATCH — do not proceed"
```

### Step 2 — Create rollback branch from current `production` HEAD

```bash
# Branch from current production HEAD (not from the backup tag)
export ROLLBACK_BRANCH="fix/rollback-${RECOVERY_POINT}"
git checkout -b $ROLLBACK_BRANCH origin/production
```

### Step 3 — Revert all commits since the backup tag

```bash
# Stage the revert of every commit between the backup tag and current production HEAD
# --no-commit stages all reversals without creating intermediate commits
git revert --no-commit -m 1 ${ROLLBACK_TAG}..HEAD

# Confirm the staged diff is the inverse of the failed remediation changes
git diff --stat HEAD

# Guard: abort if nothing was staged (production may already be at rollback state)
git diff --cached --quiet \
  && { echo "ERROR: Nothing staged — production may already be at rollback state. Verify before proceeding."; exit 1; }

# Commit the revert as a single auditable commit
git commit -m "revert: roll back to ${RECOVERY_POINT} (backup tag ${ROLLBACK_TAG})"

git push origin $ROLLBACK_BRANCH
```

> **If there are conflicts during revert:** A conflict means the failed commits partially overlapped with other changes. Resolve each conflict so that the result matches the backup tag state. Use `git show ${ROLLBACK_TAG}:<file>` to see the expected file content at the backup point.

### Step 4 — Create merge request into `production`

In GitLab (`https://dot-portal.de.pri.o2.com/gitlab/fastoss_b/ndl_core/<repo-name>`):

1. Go to **Merge Requests → New merge request**
2. Source branch: `fix/rollback-${RECOVERY_POINT}`
3. Target branch: `production`
4. Title: `Rollback to pre-remediation state (${RECOVERY_POINT})`
5. Description: reference this procedure, the backup tag, the revert commit SHA, and the incident record
6. Request approval from the required approvers

**Why MR into `production` and not a `rollback_production_*` branch:**
The current `workflow-rules.gitlab-ci.yml` permits pipeline runs only for the branches `test`, `production`, version tags, and configured topic prefixes. A branch named `rollback_production_*` is not in the permitted list and will be rejected by the pipeline. Merging into `production` triggers the standard deployment pipeline on the `production` branch, which is the correct and tested path.

> **If a dedicated rollback pipeline job is required in future**, the following changes are needed:
> - Add a `rollback/` prefix to the `workflow-rules.gitlab-ci.yml` permitted-branches list
> - Add the BQ rollback template include to `bq.gitlab-ci.yml` (currently excluded at line 62)
> - Define a `CI_COMMIT_BRANCH =~ /^rollback\//` condition in the production deploy jobs

### Step 5 — Monitor pipeline after merge

After the MR is merged into `production`:

```bash
curl --silent --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "${GITLAB_HOST}/api/v4/projects/${GITLAB_PROJECT_ID}/pipelines?ref=production&per_page=1" \
  | jq '.[0] | {id, status, sha}'
```

Or monitor in GitLab UI: **CI/CD → Pipelines → production branch**.

Expected: `status = success`.

### Step 6 — Validate deployed version

```bash
DEPLOYED_SHA=$(curl --silent --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "${GITLAB_HOST}/api/v4/projects/${GITLAB_PROJECT_ID}/repository/branches/production" \
  | jq -r '.commit.id')

echo "Deployed SHA: $DEPLOYED_SHA"
```

The deployed commit will be the revert commit (a new SHA), not the backup tag SHA — this is correct. Validate the revert commit is the one that was merged and that the pipeline ran on it.

### Step 7 — Record rollback evidence

```bash
echo "{
  \"rollback_tag\": \"${ROLLBACK_TAG}\",
  \"rollback_branch\": \"${ROLLBACK_BRANCH}\",
  \"recovery_point\": \"${RECOVERY_POINT}\",
  \"backup_tag_sha\": \"$(git rev-parse ${ROLLBACK_TAG})\",
  \"revert_commit_sha\": \"$(git rev-parse ${ROLLBACK_BRANCH})\",
  \"deployed_sha\": \"${DEPLOYED_SHA}\",
  \"pipeline_id\": \"<id>\",
  \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
}" > rollback_evidence.json

gsutil cp rollback_evidence.json \
  ${RECOVERY_BASE}/evidence/rollback_evidence.json
```

### Code rollback checklist

- [ ] Rollback tag SHA verified against `git_backup_record.json`
- [ ] Rollback branch created from `origin/production` HEAD (not from backup tag)
- [ ] `git revert --no-commit <tag>..HEAD` staged and committed as single revert commit
- [ ] No unresolved conflicts in revert commit
- [ ] MR opened into `production`
- [ ] MR approved by required approvers
- [ ] Pipeline on `production` branch: status = success
- [ ] Evidence (backup tag SHA, revert commit SHA, deployed SHA) stored in `${RECOVERY_BASE}/evidence/`

---

## Section 9 — CI/CD rollback procedure (GitLab)

The CI/CD rollback is completed as part of the code rollback in Section 8 (the MR merge into `production` triggers the deployment pipeline). This section covers monitoring and validation only.

### Step 1 — Monitor pipeline

```bash
export GITLAB_HOST="https://dot-portal.de.pri.o2.com/gitlab"
export GITLAB_TOKEN="<your-token>"
export GITLAB_PROJECT_ID="<project-id>"

curl --silent --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "${GITLAB_HOST}/api/v4/projects/${GITLAB_PROJECT_ID}/pipelines?ref=production&per_page=5" \
  | jq '.[] | {id, status, sha, created_at}'
```

### Step 2 — Validate all pipeline jobs passed

```bash
PIPELINE_ID=<id-from-step-1>

curl --silent --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "${GITLAB_HOST}/api/v4/projects/${GITLAB_PROJECT_ID}/pipelines/${PIPELINE_ID}/jobs" \
  | jq '.[] | {name, status, stage}'
```

Expected: all jobs `status = success`. Any `failed` job is a blocker.

### Step 3 — Validate data after pipeline

```bash
# Set TABLE, DATASET, and DATA_PROJECT_ID to match the tables restored in Section 6
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM \`${DATA_PROJECT_ID}.${DATASET}.${TABLE}\`"
```

### Step 4 — Retry a failed job (if needed)

In GitLab UI: **CI/CD → Pipelines → \<pipeline\> → Retry failed job**

Or via API:

```bash
JOB_ID=<failed-job-id>
curl --request POST \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "${GITLAB_HOST}/api/v4/projects/${GITLAB_PROJECT_ID}/jobs/${JOB_ID}/retry"
```

### Step 5 — If wrong version was deployed

```bash
# Create a new revert branch from origin/production and repeat Section 8 Steps 2-4
git checkout -b fix/rollback-corrected-${RECOVERY_POINT} origin/production
# Identify the correct backup tag and revert to it
git revert --no-commit -m 1 <correct_backup_tag>..HEAD
git diff --cached --quiet \
  && { echo "ERROR: Nothing staged — production may already be at rollback state. Verify before proceeding."; exit 1; }
git commit -m "revert: corrected rollback to ${RECOVERY_POINT}"
git push origin fix/rollback-corrected-${RECOVERY_POINT}
# Open a new MR into production
```

### CI/CD rollback checklist

- [ ] Pipeline triggered on `production` branch (not `rollback_production_*`)
- [ ] All pipeline jobs: status = success
- [ ] dbt models executed successfully (via Composer DAG, not local)
- [ ] Data validation queries pass
- [ ] Pipeline ID and timestamp recorded in evidence

---

## Section 10 — Important principle: sequencing

Rollback **must** follow this order:

```
1. Data      →  BigQuery restore (Section 6)
2. ETL code  →  Git rollback (Section 8) + Composer/dbt restore (Section 7)
3. Pipelines →  CI/CD deployment on production branch (Section 9)
```

**Never start ETL or pipeline rollback before data consistency is confirmed.** ETL logic depends on schema and data state — starting too early causes silent data corruption.

---

## Section 11 — Failure handling

| Symptom | Action |
|---|---|
| `bq extract` fails | Re-run the extract for the affected table only. Check job error: `bq show -j <job_id>` |
| Schema mismatch on load | Verify Parquet schema matches DDL. Use the `_ddl.sql` file, not the `_schema.json`. |
| Partition validation `diff` shows differences | Do not promote. Identify the missing partition range and re-export from source before retrying. |
| Policy tags missing after Step 4b | Verify the `_schema.json` backup contains `policyTags` entries. If absent, the backup pre-dates the policy-tag configuration; apply tags from the Data Catalog taxonomy manually. |
| Permission denied on any GCP command | **Stop. Raise an access request through the CCoE access-request procedure.** Do not run `gcloud projects add-iam-policy-binding` ad-hoc. |
| GitLab pipeline rejected (branch not permitted) | The rollback branch must target `production`. See Section 8 Step 4. Confirm the branch prefix is in the workflow rules permitted list. |
| `git revert` produces conflicts | Resolve each conflict so the file content matches `git show ${ROLLBACK_TAG}:<file>`. |
| Connection secret `MISSING` in Step 5a | Re-create the secret in Secret Manager from a secure credential source before importing connections. Do not skip — missing secrets cause all DAGs using that connection to fail silently. |
| DAG import errors after restore | Check for syntax errors, missing plugin dependencies, or incorrect environment variables. Compare Airflow variables against the backup. |
| dbt runtime errors | Verify `${COMPOSER_BUCKET}/data/dbt/` paths match what the Airflow DAG configuration expects. |
| Partial GCS copy | Re-run `gsutil -m cp -r` for the affected path. Verify with `gsutil ls` and compare against backup manifest. |

---

## Section 12 — Evidence requirements

Store all evidence under `${RECOVERY_BASE}/evidence/` in GCS and reference it in the incident / change record.

| Artefact | Location |
|---|---|
| Freeze-state inventory (active DAGs, connectors, schedules) | `${RECOVERY_BASE}/composer/freeze_state/` |
| Watermarks at freeze boundary | `${RECOVERY_BASE}/composer/freeze_state/watermarks.json` |
| Pre-backup control totals per table | `${RECOVERY_BASE}/bq/<dataset>/<table>/<table>_control_totals.json` |
| Pre-backup partition inventory per table | `${RECOVERY_BASE}/bq/<dataset>/<table>/<table>_partitions.json` |
| Connection secret references | `${RECOVERY_BASE}/composer/config/airflow_secret_refs.json` |
| Git backup record (tag + SHA) | `${RECOVERY_BASE}/gitlab/git_backup_record.json` |
| Pipeline metadata | `${RECOVERY_BASE}/gitlab/pipeline_<id>.json` |
| Restore validation results | `${RECOVERY_BASE}/evidence/restore_validation.json` |
| Rollback evidence (backup SHA, revert SHA, deployed SHA) | `${RECOVERY_BASE}/evidence/rollback_evidence.json` |

---

## Appendix A — Per-table column mapping

The control totals queries in Section 2 Step 6 (backup) and Section 6 Step 6 (restore) use `business_key` and `insert_date` as placeholder column names. These must be replaced with the actual primary-key and timestamp columns for each table before the procedure is executed.

**This mapping must be completed and kept up to date by the team responsible for the TEF datasets. It is a required companion to this procedure — without it, Steps 6 of both the backup and the restore cannot run.**

### Template

| Table | Primary key column(s) | Business timestamp column |
|---|---|---|
| `<table_name>` | `<column>` | `<column>` |

### Example (fill in for each table in scope)

| Table | Primary key column(s) | Business timestamp column |
|---|---|---|
| `sales_data` | `order_id` | `created_at` |
| `customers` | `customer_id` | `updated_at` |
| `transactions` | `transaction_id` | `transaction_date` |

When multiple columns form the primary key, use a `CONCAT()` expression in the control totals query, e.g.:

```sql
COUNT(DISTINCT CONCAT(order_id, '_', line_item_id)) AS distinct_keys
```

Tables without a single business timestamp column should use the closest available surrogate (e.g. `_PARTITIONTIME`, `load_date`, `etl_insert_ts`). Document the chosen column in the mapping above so restore validation uses the same column as backup.

---

## Section 13 — Overall success criteria

A rollback is considered successful only when **all** of the following are true:

- [ ] BigQuery: control totals `diff` produced no output (row count ± 0%)
- [ ] BigQuery: partition inventory `diff` produced no output
- [ ] BigQuery: metadata (partitioning, clustering, labels) verified
- [ ] BigQuery: column-level policy tags present on all tagged columns
- [ ] ETL: connection secrets verified in Secret Manager before connections imported
- [ ] ETL: only recorded-active DAGs and connectors resumed
- [ ] ETL: no skipped dbt models, no missing source relations
- [ ] ETL: high-water marks have advanced (not unchanged) after first run
- [ ] Code: revert commit deployed to `production` branch; pipeline = success
- [ ] Business validation: dashboards functional, no missing tables, no data gaps
- [ ] Evidence stored and referenced in the incident/change record
