# Terraform — DevOps Reports Infrastructure

This folder contains the Terraform workspace that provisions and maintains the
DevOps Reports GCP infrastructure. All resources are in the `europe-west3` region
unless stated otherwise.

---

## How to run

```bash
cd "TEF remediation/Terraform"

# First time only — initialise providers and backend
terraform init

# Preview changes before applying
terraform plan -var-file="terraform.tfvars"

# Apply changes
terraform apply -var-file="terraform.tfvars"
```

Create `terraform.tfvars` from the table in the **Variables** section below.
State is stored locally in `terraform.tfstate` (see `backend.tf`).

---

## Two-project pattern

This workspace spans **two GCP projects** with separate responsibilities:

| Variable | Project | Hosts |
|---|---|---|
| `project_id` | `tefde-gcp-fastoss-dev-gke` | Cloud Run Jobs, Cloud Scheduler, Artifact Registry, VPC connector, Secret Manager |
| `reporting_project_id` | `tefde-gcp-fastoss-dev` | BigQuery dataset, tables, views |

The split exists because the Cloud Run compute workload runs in the `-dev-gke`
project (where the Shared VPC and networking live) while the reporting data is
stored in the `-dev` project (where the data governance boundary sits).

---

## File reference

### `provider.tf`
Declares the `hashicorp/google` provider `~> 5.0` and sets the default project
and region. Requires Terraform `>= 1.4.0`.

### `backend.tf`
Configures a **local** state backend — state is stored in `terraform.tfstate`
in this folder. Keep this file out of version control when it contains sensitive
output values. If the team moves to a remote backend (GCS), update this file.

### `BQ variables.tf`
Declares all input variables for the workspace:

| Variable | Default | Description |
|---|---|---|
| `project_id` | — | Cloud Run / infra project (`tefde-gcp-fastoss-dev-gke`) |
| `reporting_project_id` | — | BigQuery / reporting project (`tefde-gcp-fastoss-dev`) |
| `bq_scan_project_id` | — | Project scanned by orphan_datasets (usually prod) |
| `region` | `europe-west3` | All resource region |
| `dataset_id` | `devops_reports` | BigQuery dataset name |
| `reports_gcs_bucket` | — | GCS bucket for CSV report outputs |
| `container_image` | — | Full Docker image URI for all Cloud Run Jobs |
| `cloud_run_sa_email` | — | Service account email for Cloud Run (provisioned by TEF IAM Team) |
| `gitlab_base_url` | Telefonica GitLab URL | GitLab API base |
| `gitlab_token_secret_id` | `gitlab-token` | Secret Manager secret holding the GitLab PAT |
| `gitlab_subgroup` | `ndl_core` | Subgroup scanned by drift reports |
| `vpc_connector_name` | `fastoss-dev-gke-connector` | VPC Access Connector (provisioned by TEF Networking Team) |
| `artifact_registry_repo_id` | `devops-reports` | Artifact Registry repository name |

### `apis.tf`
Enables the GCP APIs required before any other resource can be created.
`disable_on_destroy = false` on every resource prevents accidental service
disruption when running `terraform destroy`.

**Cloud Run / infra project** (`project_id`): Compute, VPC Access, Cloud Run,
Secret Manager, Artifact Registry, Cloud Storage, IAM, Cloud Resource Manager,
Cloud Scheduler.

**Reporting project** (`reporting_project_id`): BigQuery, IAM, Cloud Resource
Manager.

### `artifact_registry.tf`
Creates the Artifact Registry Docker repository (`devops-reports`) that stores
the devops-reports container image.

The IAM bindings (reader for the Cloud Run SA, writer for CI/CD) are **commented
out** — they are managed by the TEF IAM Team to avoid conflicts. Do not uncomment
without coordinating with that team.

Output `artifact_registry_base_url`: the base image URI to use as the prefix
for `container_image` in `terraform.tfvars`.

### `networking.tf`
Contains only a **data source lookup** — it reads the existing VPC Access
Connector (`fastoss-dev-gke-connector`) provisioned by the TEF Networking Team.
This workspace creates no network resources. The connector is referenced by all
Cloud Run Jobs to reach the private GitLab network.

The commented-out resources at the bottom are legacy VPC/firewall definitions —
kept for reference only. Do not uncomment.

### `BQ DS + Tables.tf`
The largest file. Creates and manages everything in BigQuery:

**Dataset**
- `google_bigquery_dataset.devops_reports` — dataset `devops_reports` in `reporting_project_id`

**Tables** (physical, with schema + partitioning):

| Resource | Table | Partitioned by | Clustered by |
|---|---|---|---|
| `branch_drift_kpis` | One KPI row per repo × direction × run | `run_date` | `repo`, `drift_type` |
| `branch_drift_evidence` | One row per drifting file/commit per run | `run_date` | `repo`, `discrepancy` |
| `executions` | One row per Cloud Run Job execution | `execution_ts` | `report_type`, `status` |
| `orphan_datasets` | One row per orphaned BQ dataset | `execution_id` | — |
| `orphan_dataset_objects` | One row per object in an orphaned dataset | — | — |
| `bq_structure_drift` | Schema drift across environments | `checked_at` | `dataset_id` |

**Views** (Looker Studio data sources):

| Resource | View | Purpose |
|---|---|---|
| `env_drift_report` | `env_drift_report` | GCS + BQ environment vs source drift (prod) |
| `env_drift_test_report` | `env_drift_test_report` | Same for test environment |
| `env_drift_dev_report` | `env_drift_dev_report` | Same for dev environment |
| `orphan_datasets_report` | `orphan_datasets_report` | Orphan dataset findings |
| `commit_drift_report` | `commit_drift_report` | Commit-based branch drift KPIs |
| `commit_drift_evidence_report` | `commit_drift_evidence_report` | Commit-level drill-through |
| `file_drift_report` | `file_drift_report` | File-content branch drift KPIs |
| `file_drift_evidence_report` | `file_drift_evidence_report` | File-level drill-through (remediation) |
| `bq_structure_drift_report` | `bq_structure_drift_report` | BQ schema drift across environments |

> When updating a view's SQL, edit the `query` heredoc inside the corresponding
> `google_bigquery_table` resource and run `terraform apply`. The view is updated
> in place with no data loss.

### `Cloud Run Jobs.tf`
Defines six Cloud Run v2 Jobs, all sharing the same `container_image` variable
and `cloud_run_sa_email` service account. Each job passes a different first
argument to `entrypoint.sh` to select the report type.

| Job name (GCP) | Report | Schedule |
|---|---|---|
| `devops-reports-orphan-datasets` | Orphan BQ datasets | 05:00 |
| `devops-reports-dataset-mapping` | Dataset → repo mapping | on-demand |
| `devops-reports-env-drift` | Environment vs code drift (prod) | 05:10 |
| `devops-reports-env-drift-test` | Environment vs code drift (test) | 05:40 |
| `devops-reports-env-drift-dev` | Environment vs code drift (dev) | 05:50 |
| `devops-reports-commit-drift` | Commit-based branch drift | 05:20 |
| `devops-reports-file-drift` | File-content branch drift | 05:30 |

The `env_drift` jobs use 4 GiB / 2 CPU (more headroom for parallel repo processing).
All other jobs use 2 GiB / 1 CPU.

All jobs route egress through the Shared VPC (`ALL_TRAFFIC` egress via the VPC
Access Connector) so they can reach the private GitLab instance.

To rebuild the Docker image and update all jobs, push a new image tag and update
`container_image` in `terraform.tfvars`, then run `terraform apply`.

### `scheduler.tf`
Creates seven Cloud Scheduler jobs that trigger the Cloud Run Jobs daily via the
Cloud Run Admin API (`POST .../jobs/{job}:run`). Authentication uses `oauth_token`
(not OIDC) because the target is a Google API endpoint.

Schedules are staggered by 10 minutes from 05:00 to 05:50 CET to avoid
simultaneous clone load on the GitLab server.

### `looker.tf`
Contains only comments — Looker Studio dashboards require no GCP Terraform
resources. Dashboards are built manually in Looker Studio and connect to the
BigQuery views defined in `BQ DS + Tables.tf`. See the `Instructions/` folder
for step-by-step dashboard creation guides.

---

## What is NOT managed here

The following are owned by other teams and must not be created or modified
in this workspace:

| Resource | Owner |
|---|---|
| Service account `devops-reports-runner@...` | TEF IAM Team |
| IAM role bindings on the service account | TEF IAM Team |
| Artifact Registry IAM (reader/writer) | TEF IAM Team |
| VPC Access Connector | TEF Networking Team |
| Shared VPC network and subnets | TEF Networking Team |
| Firewall rules on the Shared VPC | TEF Networking Team |
| GitLab PAT value in Secret Manager | Secret is created here; value loaded manually |

---

## Related

- `TEF remediation/Dockerfile.python` — Docker image built from this repo
- `TEF remediation/git_gcp_code_vs_environment_drift/` — env drift Python script
- `TEF remediation/git_branches_gap/` — branch drift Python scripts
- `Instructions/Building and Releasing a New Image Version.md` — how to rebuild and deploy the Docker image
- `Instructions/Running Cloud Run Jobs.md` — how to trigger jobs manually
