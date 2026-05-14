# README.md

```markdown
# Environment Drift & Governance Reporting

This repository contains a **Cloud‑native drift and governance reporting framework**
for BigQuery- and GCS-based data products.

It is designed to:
- Detect **environment drift** between source code and deployed environments
- Detect **orphan BigQuery datasets** with no source ownership
- Run in **Docker / Cloud Run Jobs**
- Be **triggered from a UI**
- Persist results in **BigQuery for analytics and governance**

---

## What Problems This Solves

This project addresses four governance and reliability use cases:

1. **Environment vs Branch Drift**  
   Are deployed BigQuery objects and GCS artifacts consistent with source code?

2. **Commit / Branch Drift (environment‑centric)**  
   Does a specific Git ref diverge from what is deployed?

3. **File‑level Drift Detection**  
   Are generated artifacts semantically different after normalization?

4. **Orphan BigQuery Datasets** ✅  
   Which datasets exist in BigQuery **without any source code ownership**, even if source code is lost?

---

## Report Types

### 1️⃣ Environment vs Branch Drift Report

Detects discrepancies between:
- **Source snapshot** (Git branch or Nexus release)
- **Runtime environment** (BigQuery + GCS)

Findings include:
- Missing objects
- Extra objects
- Schema mismatches
- Definition mismatches
- Artifact content drift

---

### 2️⃣ Orphan BigQuery Datasets Report

Detects datasets that:
- Exist in a BigQuery project
- Are **not referenced** by any repository via `BQ_DATASET_NAMES`
- Are evaluated at a specific Git ref (e.g. `production`)

This report works even when:
- Repositories are missing
- Code history is incomplete
- Only CI/CD metadata remains

---

## Architecture Overview

```

┌──────────┐
│   UI     │
│ (Portal) │
└────┬─────┘
│ Cloud Run Job trigger
▼
┌────────────────────────────┐
│ Cloud Run Job (Docker)     │
│                            │
│ - env drift script         │
│ - orphan dataset script    │
└────┬───────────────┬───────┘
│               │
▼               ▼
┌──────────────┐  ┌──────────┐
│ Git / Nexus  │  │ BigQuery │
│ Source Code  │  │ Runtime  │
└──────────────┘  └────┬─────┘
▼
┌────────────────────┐
│ devops\_reports BQ  │
│ - executions       │
│ - env\_drift\_findings│
└────────────────────┘

```

---

## BigQuery Reporting Model

All reports write into a **single reporting dataset**:

```

devops\_reports

```

### Tables

#### `executions`
One row per report execution.

Tracks:
- execution_id
- report_type (`env_drift`, `orphan_datasets`)
- execution_ts
- environment
- git_ref
- source_mode
- status

---

#### `env_drift_findings`
One row per detected issue or governance finding.

Logical usage:

| component_type       | drift_category     | Meaning                          |
|---------------------|--------------------|----------------------------------|
| bigquery            | schema_mismatch…   | BigQuery object drift            |
| gcs                 | content_mismatch…  | GCS artifact drift               |
| bigquery_dataset    | orphan_dataset     | Dataset has no source ownership  |

✅ No additional tables are required to add new report types.

---

## Scripts

### `git_gcp_code_vs_environment_drift.py`

Primary **environment drift engine**.

Responsibilities:
- Render source snapshot (Git or Nexus)
- Build inventories (BigQuery, dbt, Python)
- Compare against runtime environment
- Emit drift findings

---

### `unmatched_bq_datasets_report.py`

**Orphan BigQuery Datasets** governance report.

Responsibilities:
- List datasets in BigQuery
- Scan multiple repositories
- Read `.gitlab-ci.yml` at a Git ref
- Extract `BQ_DATASET_NAMES`
- Detect datasets with no source ownership

---

## Execution Model

All scripts:
- Run as **Docker containers**
- Are executed via **Cloud Run Jobs**
- Require a UI‑provided `EXECUTION_ID`
- Write structured results to BigQuery

Execution status:
- `success` → report completed
- `failed` → execution aborted (recorded)

---

## Docker Image

Common runtime image:
- Python 3.11 slim
- git, curl
- `google-cloud-bigquery`

Authentication:
- **Workload Identity**
- No credentials baked into image

---

## IAM & Security

### Cloud Run Job Service Account

**Reporting project**:
- `roles/bigquery.dataEditor`
- `roles/bigquery.jobUser`

**Runtime project**:
- `roles/bigquery.metadataViewer`
- `roles/storage.objectViewer`

---

## UI Integration

### Required Environment Variable

```

EXECUTION\_ID

```

### Typical UI‑to‑Job Arguments

- `--project-id`
- `--reporting-project`
- `--workspace-root`
- `--subgroup`
- `--git-ref`

The UI treats each execution as an **immutable audit record**.

---

## Looker & Analytics

All reporting data is **Looker‑ready**.

Typical dashboards:
- Environment Drift Overview
- Orphan Dataset Governance
- High‑Severity Drift Alerts
- Trend & Cleanup Progress

Example SQL queries are documented in:
**Environment Drift Reporting – Updated Technical Documentation**

---

## Final Notes

This repository intentionally separates:
- **Drift detection** (source vs environment)
- **Governance detection** (ownership gaps)

This keeps the system:
- Scalable
- Auditable
- Easy to extend with new report types

---

*End of README.*