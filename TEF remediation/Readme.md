# DevOps Governance & Drift Reporting Framework

A cloud-native reporting framework that detects drift and governance gaps across Git branches, GCP environments, and BigQuery datasets. All reports run as **Google Cloud Run Jobs**, write results to **BigQuery** and **GCS**, and are visualised in **Looker Studio**.

---

## Reports

All 4 reports run automatically every day via Cloud Scheduler (`scheduler.tf`). They can be
triggered manually via `gcloud run jobs execute`. Schedule times are `Europe/Berlin`.

| # | Report | Script | Cloud Run job name | Daily schedule |
|---|---|---|---|---|
| 1 | Commit-based branch drift | `git_branches_gap/report_branch_discrepancies_by_commit.py` | `devops-reports-commit-drift` | 05:20 |
| 2 | File-content branch drift | `git_branches_gap/report_branch_discrepancies_by_content.py` | `devops-reports-file-drift` | 05:30 |
| 3 | Environment vs code drift | `git_gcp_code_vs_environment_drift/generate_code_environment_drift_report.py` | `devops-reports-env-drift` | 05:10 |
| 4 | Orphan BigQuery datasets | `bigquery_orphan_datasets/unmatched_bq_datasets_report.py` | `devops-reports-orphan-datasets` | 05:00 |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Cloud Scheduler                                        │
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
| Cloud Run Jobs, GCS, Secret Manager, Artifact Registry | `tefde-gcp-fastoss-dev-gke` |
| Service Account *(external, TEF IAM Team)* | `tefde-gcp-resvadm-prod-backend` |
| BigQuery dataset and tables | `tefde-gcp-fastoss-dev` |
| BigQuery datasets scanned for orphans | `tefde-gcp-fastoss-prod` |
| Cloud Composer bucket read by env_drift *(external, TEF IAM Team grant)* | `tefde-gcp-fastoss-prod-gke` |
| Shared VPC host *(external, TEF Networking Team)* | `tefde-gcp-network-shared-ic-1` |

---

## Folder Structure

```
TEF remediation/
├── Dockerfile.python                        # Single image for all 4 Cloud Run Jobs; sets HOME=/workspace for non-root gcloud access
├── entrypoint.sh                            # Routes report type → script; env_drift runs repos in parallel (capped at ENV_DRIFT_MAX_PARALLEL, default 5)
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
├── IAM_admin_instructions.md               # Manual IAM grant instructions for GCP admins
│
├── scripts/                                # One-off utility scripts (run manually from Cloud Shell — not deployed to Cloud Run)
│   ├── README.md                           # Full usage guide for all scripts
│   ├── backfill_env_drift_report_links.py  # Backfills gcs_report_path for historical env_drift rows that have NULL
│   ├── copy_composer_dags.py               # Copies prod Composer DAGs to test/dev bucket with env-name substitution
│   ├── composer_dag_status_report.py       # Snapshot report of latest DAG run status for all Composer environments
│   ├── generate_dataset_mapping.py         # Cloud Run job: reads BQ_DATASET_NAMES from all repos, writes dataset→repo JSON to GCS
│   ├── organize_tf_export.py               # Reorganises gcloud bulk-export .tf files into nested {env}/{repo}/BigQueryTable/{dataset}/ folders
│   ├── organize_tf_export_flat.py          # Variant of above: flat layout — all files in {env}/{repo}/ with ds_/t_/r_ prefix
│   ├── propagate_tf_env.py                 # Copies prod/ flat-export to prod_dev-gke/ and prod_test/, substituting the env token throughout
│   ├── export_bq_to_tf.py                  # Supplements gcloud bulk-export: queries BQ API directly and generates HCL for all datasets/tables/routines
│   └── compare_bq_structure.py             # Compares partitioning & clustering across prod/test/dev-gke; writes drift rows to devops_reports.bq_structure_drift
│
└── Terraform/
    ├── BQ variables.tf       # All input variables
    ├── BQ DS + Tables.tf     # Secret Manager, GCS, BigQuery dataset + tables (deletion_protection = true); IAM bindings commented out — managed by TEF IAM Team
    ├── Cloud Run Jobs.tf     # 4 Cloud Run Job resources (VPC egress via connector)
    ├── scheduler.tf          # Daily Cloud Scheduler triggers for the 4 report jobs; IAM binding commented out — managed by TEF IAM Team
    ├── artifact_registry.tf  # Artifact Registry repo; IAM bindings commented out — managed by TEF IAM Team
    ├── networking.tf         # Data source for the Networking Team's VPC Access Connector (Shared VPC)
    ├── apis.tf               # GCP API enablement (both projects)
    ├── looker.tf             # Comment only — Looker Studio needs no SA
    ├── backend.tf            # Terraform state backend
    ├── provider.tf           # Google provider configuration
    └── terraform.tfvars      # Values for all variables
```

---

## Deployment Steps

### 1. Confirm networking is provisioned

Networking is provisioned externally by the TEF Networking Team — this Terraform
workspace only reads the existing VPC Access Connector via a data source:

```hcl
vpc_connector_name = "fastoss-dev-gke-connector"   # already set in terraform.tfvars
```

The connector is attached to the Shared VPC `tefde-gcp-network-shared-ic-1-vpc-devlowapp`
(host project `tefde-gcp-network-shared-ic-1`). No further action is required unless
the Networking Team renames or recreates the connector.

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

### 5. Build and push the Docker image

Images are built automatically by the CI pipeline on every commit to the default branch. To build manually:

```bash
SHA=$(git rev-parse --short HEAD)
IMAGE=europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports
docker build -f Dockerfile.python --build-arg BUILD_SHA=$SHA -t $IMAGE:$SHA -t $IMAGE:latest .
docker push $IMAGE:$SHA && docker push $IMAGE:latest
```

### 6. Connect Looker Studio to BigQuery

No service account key is required. Looker Studio uses the dashboard creator's own Google identity.

1. Looker Studio → Create → Data Source → BigQuery
2. Select project `tefde-gcp-fastoss-dev` → dataset `devops_reports`
3. Choose the table or view for the dashboard (see the BigQuery Reporting Model table below for recommendations per report type)
4. Share the dashboard (access is controlled in Looker Studio, not GCP IAM)

**Commit drift and file drift dashboards** — connect directly to the `commit_drift_report` and `file_drift_report` views (no Custom Query needed). Both views include a `run_number` field (1 = latest run for that date, 2 = previous run, …). Add two Filter Controls to the dashboard:
- `run_date` — date picker to select the day
- `run_number` — drop-down to select the specific run within that day

> "Enable date range parameters" must be **UNCHECKED** on these data sources.

The `looker_sql/` SQL files remain as reference but are no longer the primary data source for these two dashboards.

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
| `build` | `build-reports` | Changes to `Dockerfile.python`, `requirements.txt`, report scripts, or `entrypoint.sh` |
| `terraform` | `terraform-plan` | Changes under `Terraform/` |
| `release` | `create-release` | Tag push matching `v*` |

Each build job runs a **Trivy** vulnerability scan between `docker build` and `docker push`. HIGH and CRITICAL CVEs block the push.

To publish a release:
```bash
git tag -a v3.1.0 -m "Release v3.1.0: <summary>"
git push origin main && git push origin v3.1.0
```
GitLab CI creates the release object automatically from the annotated tag message.

---

## BigQuery Reporting Model

All 4 reports write into `devops_reports` in `tefde-gcp-fastoss-dev`, located in `europe-west3` (single-region — the org policy `constraints/gcp.resourceLocations` does not permit multi-region locations like `EU`). All tables have `deletion_protection = true` except the `execution_daily_summary` view, which has no underlying storage to protect.

| Table / View | Purpose |
|---|---|
| `executions` | One row per job run: `triggered_by`, `duration_seconds`, `gcs_path`, and `status` (`success` / `failed` / `skipped` — env_drift writes `skipped` for repos that have no `production` branch, which is expected for staging/demo projects) |
| `branch_drift_kpis` | Commit/file drift counts per repo × direction |
| `branch_drift_evidence` | Individual commits/files driving the drift |
| `env_drift_findings` | Code vs environment discrepancies |
| `orphan_datasets` | Unowned BigQuery datasets |
| `orphan_dataset_objects` | Objects inside orphan datasets |
| `entities` | Reference catalogue |
| `execution_daily_summary` *(view)* | Daily success/failure rates per report type — connect directly to Looker Studio |
| `env_drift_summary` *(view)* | Per-repository env-drift summary: `bq_findings`, `gcs_findings`, `run_number`, and `report_url` (authenticated GCS link to the report file). Use as a Looker Studio data source for the env-drift dashboard. |
| `commit_drift_report` *(view)* | Per-repo × drift-direction commit drift detail with `run_number` (1 = latest run for that date, 2 = previous, …). Use as Looker Studio data source for the commit drift dashboard; add Filter Controls on `run_date` and `run_number`. |
| `commit_drift_evidence_report` *(view)* | One row per file per commit — evidence level drill-through. Columns: `repo`, `drift_direction` (⚠ prefix on the 3 critical directions), `commit_sha`, `author`, `commit_date`, `file_path`. Use as a second data source on the commit drift dashboard for the evidence table. |
| `file_drift_report` *(view)* | Per-repo × drift-direction file drift detail with `run_number`. Same Filter Control setup as `commit_drift_report`. Includes `files_added`, `files_modified`, `files_deleted`, `files_other`. |
| `management_dashboard` *(view)* | Management red/green health grid: joins env drift, commit drift, and file drift per repo × date into a single row with a `status` column (`All clear` / `Has findings`). Use as a Looker Studio data source for the executive summary dashboard. |
| `bq_structure_drift` | One row per discrepancy per run: partitioning and clustering differences (or missing tables) across prod, test, and dev-gke. Partitioned by `checked_at` (DAY), clustered by `dataset_id`. Written by `compare_bq_structure.py`. |
| `bq_structure_drift_report` *(view)* | Adds `run_date` and `run_number` (1 = latest run for that dataset/table/attribute). Use as Looker Studio data source; add Filter Controls on `run_date` and `run_number`. |

---

## Service Account

A single service account `devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com` is used for:
- Cloud Run Jobs runtime (Workload Identity — no key required)
- CI/CD image pushes to Artifact Registry (JSON key stored as `GCP_SA_KEY` in GitLab CI)
- Identity that Cloud Scheduler runs the 4 report jobs as, once a day

> **The service account is created and owned by the TEF IAM Team.** It is not managed by this Terraform workspace. All IAM binding resources in Terraform are commented out for reference only — the TEF IAM Team applies the actual grants manually.

The Terraform deployer identity also requires `roles/iam.serviceAccountUser` on the SA (Grant #10 in `IAM_admin_instructions.md`) to allow Cloud Run to be assigned this SA during `terraform apply`. Cloud Scheduler additionally requires `roles/iam.serviceAccountTokenCreator` on the SA, granted to the Cloud Scheduler service agent (Grant #11) — without it, daily scheduled runs fail with a 403 at firing time.

See `IAM_admin_instructions.md` for the full list of IAM grants required.

---

## Security

- No credentials baked into Docker images
- GitLab PAT stored in **GCP Secret Manager**, fetched at runtime; redacted from git subprocess error output before reaching Cloud Logging
- Cloud Run Jobs use **Workload Identity** — no long-lived credentials at runtime
- Trivy scans for HIGH/CRITICAL CVEs on every image build, blocking push on findings
- BigQuery tables protected with `deletion_protection = true`
- All BigQuery, GCS, and Secret Manager resources are pinned to the single region **`europe-west3`**, required by org policy `constraints/gcp.resourceLocations` — multi-region locations such as `EU` are not permitted
- Network connectivity (Shared VPC, subnet, VPC Access Connector, firewall/egress policy) is provisioned and managed centrally by the TEF Networking Team
- `EXECUTION_ID` dedup guard prevents double-writes on Cloud Run retries
- `EXECUTION_ID` is auto-generated per run (UUID4 via Python)
