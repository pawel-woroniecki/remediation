# DevOps Governance & Drift Reporting Framework

A cloud-native reporting framework that detects drift and governance gaps across Git branches, GCP environments, and BigQuery datasets. All reports run as **Google Cloud Run Jobs**, write results to **BigQuery** and **GCS**, and are visualised in **Looker**.

---

## Reports

| # | Report | Script | Cloud Run job name |
|---|---|---|---|
| 1 | Commit-based branch drift | `git_branches_gap/report_branch_discrepancies_by_commit.py` | `devops-reports-commit-drift` |
| 2 | File-content branch drift | `git_branches_gap/report_branch_discrepancies_by_content.py` | `devops-reports-file-drift` |
| 3 | Environment vs code drift | `git_gcp_code_vs_environment_drift/generate_code_environment_drift_report.py` | `devops-reports-env-drift` |
| 4 | Orphan BigQuery datasets | `bigquery_orphan_datasets/unmatched_bq_datasets_report.py` | `devops-reports-orphan-datasets` |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  UI / Cloud Scheduler                                   │
└────────────────────┬────────────────────────────────────┘
                     │  trigger Cloud Run Job
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Cloud Run Job  (tefde-gcp-fastoss-dev-gke)             │
│  Docker image ← Artifact Registry                       │
│                                                         │
│  entrypoint.sh                                          │
│    Phase 1: clone_fastoss_b.py  (all repos via GitLab)  │
│    Phase 2: report script                               │
└──────┬──────────────────────────────┬───────────────────┘
       │                              │
       ▼                              ▼
┌─────────────┐            ┌──────────────────────────────┐
│ Secret Mgr  │            │  BigQuery  (tefde-gcp-        │
│ gitlab-token│            │  fastoss-dev)                 │
└─────────────┘            │  dataset: devops_reports      │
                           │  - executions                 │
       ▼                   │  - branch_drift_kpis          │
┌─────────────┐            │  - branch_drift_evidence      │
│  GCS bucket │            │  - env_drift_findings         │
│  CSV outputs│            │  - orphan_datasets            │
└─────────────┘            │  - orphan_dataset_objects     │
                           └──────────────┬────────────────┘
                                          │
                                          ▼
                                    ┌──────────┐
                                    │  Looker  │
                                    └──────────┘
```

---

## GCP Projects

| Resource | Project |
|---|---|
| Cloud Run Jobs, GCS, Secret Manager, Service Account, Artifact Registry | `tefde-gcp-fastoss-dev-gke` |
| BigQuery dataset and tables | `tefde-gcp-fastoss-dev` |

---

## Folder Structure

```
TEF remediation/
├── Dockerfile.python                        # Single image for all 4 reports
├── entrypoint.sh                            # Routes report type → script
├── requirements.txt                         # Python dependencies
│
├── clone_all_groups_repo/
│   ├── clone_fastoss_b.py                   # Clones all repos (reads PAT from Secret Manager)
│   └── clone_fastoss_b.ps1                  # Local dev use only
│
├── git_branches_gap/
│   ├── report_branch_discrepancies_by_commit.py   # Cloud Run: commit drift
│   ├── report_branch_discrepancies_by_content.py  # Cloud Run: file drift
│   └── *.ps1                                      # Local dev scripts
│
├── git_gcp_code_vs_environment_drift/
│   └── generate_code_environment_drift_report.py  # Cloud Run: env drift
│
├── bigquery_orphan_datasets/
│   └── unmatched_bq_datasets_report.py            # Cloud Run: orphan datasets
│
├── looker_sql/
│   ├── commit_drift_report.sql
│   ├── file_drift_report.sql
│   ├── env_drift_report.sql
│   └── orphan_datasets_report.sql
│
└── Terraform/
    ├── BQ variables.tf       # Provider, all variables
    ├── BQ DS + Tables.tf     # SA, Secret Manager, GCS, BigQuery, IAM
    ├── Cloud Run Jobs.tf     # 4 Cloud Run Job resources
    ├── artifact_registry.tf  # Artifact Registry repo + IAM
    ├── apis.tf               # GCP API enablement (both projects)
    ├── looker.tf             # Looker read-only SA + BQ IAM
    └── terraform.tfvars      # Values for all variables
```

---

## Deployment Steps

### 1. Terraform apply

```bash
cd "TEF remediation/Terraform"
terraform init
terraform apply
```

### 2. Load the GitLab PAT into Secret Manager

```bash
gcloud secrets versions add gitlab-token \
  --project=tefde-gcp-fastoss-dev-gke \
  --data-file=- <<< "YOUR_GITLAB_PAT"
```

### 3. Build and push the Docker image

```bash
docker build -f Dockerfile.python -t \
  europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports:latest .

docker push \
  europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports:latest
```

### 4. Create the Looker BigQuery key (manual — cannot be done in Terraform)

```bash
gcloud iam service-accounts keys create looker-bq-reader-key.json \
  --iam-account=looker-bq-reader@tefde-gcp-fastoss-dev.iam.gserviceaccount.com \
  --project=tefde-gcp-fastoss-dev
```

Upload `looker-bq-reader-key.json` to **Looker Admin → Connections → BigQuery**.

### 5. Run a report manually

```bash
gcloud run jobs execute devops-reports-commit-drift \
  --project=tefde-gcp-fastoss-dev-gke \
  --region=europe-west3
```

---

## BigQuery Reporting Model

All 4 reports write into `devops_reports` in `tefde-gcp-fastoss-dev`.

| Table | Purpose |
|---|---|
| `executions` | One row per job run — audit trail |
| `branch_drift_kpis` | Commit/file drift counts per repo × direction |
| `branch_drift_evidence` | Individual commits/files driving the drift |
| `env_drift_findings` | Code vs environment discrepancies |
| `orphan_datasets` | Unowned BigQuery datasets |
| `orphan_dataset_objects` | Objects inside orphan datasets |
| `entities` | Reference catalogue |

---

## Security

- No credentials baked into the Docker image
- GitLab PAT stored in **GCP Secret Manager**, fetched at runtime
- Cloud Run Jobs use **Workload Identity** via the `devops-reports-runner` service account
- Looker uses a dedicated read-only service account (`looker-bq-reader`)
- `EXECUTION_ID` is auto-generated by `entrypoint.sh` on every run using `uuidgen`
