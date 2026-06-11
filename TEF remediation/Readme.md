# DevOps Governance & Drift Reporting Framework

A cloud-native reporting framework that detects drift and governance gaps across Git branches, GCP environments, and BigQuery datasets. All reports run as **Google Cloud Run Jobs**, write results to **BigQuery** and **GCS**, and are visualised in **Looker Studio**.

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
│  UI (devops-reports-ui) / Cloud Scheduler               │
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
│             (env_drift runs repos in parallel)          │
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
                                  ┌─────────────────┐
                                  │  Looker Studio  │
                                  │  (viewer OAuth) │
                                  └─────────────────┘
```

---

## GCP Projects

| Resource | Project |
|---|---|
| Cloud Run Jobs, UI Service, GCS, Secret Manager, Service Account, Artifact Registry | `tefde-gcp-fastoss-dev-gke` |
| BigQuery dataset and tables | `tefde-gcp-fastoss-dev` |
| BigQuery datasets scanned for orphans | `tefde-gcp-fastoss-prod` |

---

## Folder Structure

```
TEF remediation/
├── Dockerfile.python                        # Single image for all 4 Cloud Run Jobs
├── entrypoint.sh                            # Routes report type → script; env_drift runs repos in parallel
├── .gitlab-ci.yml                           # CI: build + Trivy scan + Terraform plan + GitLab release
├── .gitignore                               # Excludes tfstate, SA key files, Python artefacts
├── requirements.txt                         # Python dependencies
│
├── clone_all_groups_repo/
│   ├── clone_fastoss_b.py                   # Clones all repos (reads PAT from Secret Manager; redacts token from error logs)
│   └── clone_fastoss_b.ps1                  # Local dev use only
│
├── git_branches_gap/
│   ├── report_branch_discrepancies_by_commit.py   # Cloud Run: commit drift
│   ├── report_branch_discrepancies_by_content.py  # Cloud Run: file drift
│   └── *.ps1                                      # Local dev scripts
│
├── git_gcp_code_vs_environment_drift/
│   └── generate_code_environment_drift_report.py  # Cloud Run: env drift (one execution per repo)
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
├── ui/
│   ├── main.py                              # FastAPI backend
│   ├── reports.yaml                         # Declarative report + parameter metadata
│   ├── static/index.html                    # Single-page frontend
│   ├── requirements.txt                     # UI Python dependencies
│   └── Dockerfile                           # UI container image
│
├── IAM_admin_instructions.md               # Manual IAM grant instructions for GCP admins
│
└── Terraform/
    ├── BQ variables.tf       # All input variables
    ├── BQ DS + Tables.tf     # Secret Manager, GCS, BigQuery dataset + tables (deletion_protection = true); IAM bindings commented out — managed by TEF IAM Team
    ├── Cloud Run Jobs.tf     # 4 Cloud Run Job resources (VPC egress via connector)
    ├── ui_service.tf         # UI Cloud Run Service + IAM (restricted to domain:telefonica.de)
    ├── artifact_registry.tf  # Artifact Registry repo + IAM
    ├── networking.tf         # Dedicated VPC, subnet, VPC Access Connector, firewall rules
    ├── apis.tf               # GCP API enablement (both projects)
    ├── looker.tf             # Comment only — Looker Studio needs no SA
    ├── backend.tf            # Terraform state backend
    ├── provider.tf           # Google provider configuration
    └── terraform.tfvars      # Values for all variables
```

---

## Deployment Steps

### 1. Fill in required placeholder values in `terraform.tfvars`

Before applying Terraform, set the GitLab network CIDR:

```hcl
gitlab_network_cidr = "10.x.x.x/xx"   # ask your network team
```

### 2. Terraform apply

```bash
cd "TEF remediation/Terraform"
terraform init
terraform validate
terraform apply
```

### 3. Load the GitLab PAT into Secret Manager

```bash
gcloud secrets versions add gitlab-token \
  --project=tefde-gcp-fastoss-dev-gke \
  --data-file=- <<< "YOUR_GITLAB_PAT"
```

The PAT requires `read_api` and `read_repository` scopes. Prefer a **Group Access Token** over a Personal Access Token.

### 4. Create a key for `devops-reports-runner` (used by CI/CD to push images)

> **Note:** The service account `devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com` is created and owned by the **TEF IAM Team**. Request the key from that team or ask them to generate it.

```bash
gcloud iam service-accounts keys create runner-key.json \
  --iam-account=devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com \
  --project=tefde-gcp-resvadm-prod-backend
```

Add the contents of `runner-key.json` as the `GCP_SA_KEY` **masked** variable in GitLab CI/CD settings, then delete the local file. See `.gitlab-ci.yml` for the Workload Identity Federation upgrade path that eliminates this key.

### 5. Build and push the Docker images

Images are built automatically by the CI pipeline on every commit to the default branch. To build manually:

```bash
SHA=$(git rev-parse --short HEAD)

# Reports image
IMAGE=europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports
docker build -f Dockerfile.python --build-arg BUILD_SHA=$SHA -t $IMAGE:$SHA -t $IMAGE:latest .
docker push $IMAGE:$SHA && docker push $IMAGE:latest

# UI image
IMAGE=europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports-ui
docker build -f ui/Dockerfile --build-arg BUILD_SHA=$SHA -t $IMAGE:$SHA -t $IMAGE:latest ui/
docker push $IMAGE:$SHA && docker push $IMAGE:latest
```

### 6. Connect Looker Studio to BigQuery

No service account key is required. Looker Studio uses the dashboard creator's own Google identity.

1. Looker Studio → Create → Data Source → BigQuery
2. Select project `tefde-gcp-fastoss-dev` → dataset `devops_reports`
3. Choose a table (e.g. `execution_daily_summary`) or write a custom query using the SQL in `looker_sql/`
4. Share the dashboard (access is controlled in Looker Studio, not GCP IAM)

### 7. Run a report manually

```bash
gcloud run jobs execute devops-reports-commit-drift \
  --project=tefde-gcp-fastoss-dev-gke \
  --region=europe-west3
```

---

## CI/CD Pipeline (`.gitlab-ci.yml`)

| Stage | Job | Trigger |
|---|---|---|
| `build` | `build-reports` | Changes to `Dockerfile.python`, report scripts, or `entrypoint.sh` |
| `build` | `build-ui` | Changes under `ui/` |
| `terraform` | `terraform-plan` | Changes under `Terraform/` |
| `release` | `create-release` | Tag push matching `v*` |

Each build job runs a **Trivy** vulnerability scan between `docker build` and `docker push`. HIGH and CRITICAL CVEs block the push.

To publish a release:
```bash
git tag -a v1.2.0 -m "Release v1.2.0: <summary>"
git push origin v1.2.0
```
GitLab CI creates the release object automatically from the annotated tag message.

---

## BigQuery Reporting Model

All 4 reports write into `devops_reports` in `tefde-gcp-fastoss-dev`. All tables have `deletion_protection = true`.

| Table / View | Purpose |
|---|---|
| `executions` | One row per job run: `triggered_by`, `duration_seconds`, `status`, `gcs_path` |
| `branch_drift_kpis` | Commit/file drift counts per repo × direction |
| `branch_drift_evidence` | Individual commits/files driving the drift |
| `env_drift_findings` | Code vs environment discrepancies |
| `orphan_datasets` | Unowned BigQuery datasets |
| `orphan_dataset_objects` | Objects inside orphan datasets |
| `entities` | Reference catalogue |
| `execution_daily_summary` *(view)* | Daily success/failure rates per report type — connect directly to Looker Studio |

---

## Service Account

A single service account `devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com` is used for:
- Cloud Run Jobs runtime (Workload Identity — no key required)
- UI Cloud Run Service runtime (Workload Identity)
- CI/CD image pushes to Artifact Registry (JSON key stored as `GCP_SA_KEY` in GitLab CI)

> **The service account is created and owned by the TEF IAM Team.** It is not managed by this Terraform workspace. All IAM binding resources in Terraform are commented out for reference only — the TEF IAM Team applies the actual grants manually.

The Terraform deployer identity also requires `roles/iam.serviceAccountUser` on the SA (Grant #10 in `IAM_admin_instructions.md`) to allow Cloud Run to be assigned this SA during `terraform apply`.

See `IAM_admin_instructions.md` for the full list of IAM grants required.

---

## Security

- No credentials baked into Docker images
- GitLab PAT stored in **GCP Secret Manager**, fetched at runtime; redacted from git subprocess error output before reaching Cloud Logging
- Cloud Run Jobs and UI use **Workload Identity** — no long-lived credentials at runtime
- UI access restricted to **`domain:telefonica.de`** Google Workspace accounts
- Trivy scans for HIGH/CRITICAL CVEs on every image build, blocking push on findings
- BigQuery tables protected with `deletion_protection = true`
- Dedicated VPC with explicit-deny egress — only GitLab CIDR and Google APIs permitted
- `EXECUTION_ID` dedup guard prevents double-writes on Cloud Run retries
- `EXECUTION_ID` is auto-generated per run (UUID4 via Python)
