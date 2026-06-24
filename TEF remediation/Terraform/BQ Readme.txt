# Terraform — DevOps Reports Infrastructure

Provisions all GCP infrastructure for the devops-reports framework across two projects.

---

## Files

| File | Contents |
|---|---|
| `BQ variables.tf` | All input variables |
| `BQ DS + Tables.tf` | Secret Manager (europe-west3), GCS bucket, BigQuery dataset + 8 tables; IAM bindings commented out — managed by TEF IAM Team |
| `Cloud Run Jobs.tf` | 4 Cloud Run Job resources (one per report type) |
| `ui_service.tf` | UI Cloud Run Service + invoker IAM; run.developer binding commented out — managed by TEF IAM Team |
| `artifact_registry.tf` | Artifact Registry Docker repository; IAM bindings commented out — managed by TEF IAM Team |
| `networking.tf` | Data source for the Networking Team's VPC Access Connector (Shared VPC) |
| `apis.tf` | GCP API enablement for both projects |
| `looker.tf` | Comment only — Looker Studio requires no service account |
| `backend.tf` | Terraform state backend |
| `provider.tf` | Google provider configuration |
| `terraform.tfvars` | Variable values — fill in before running |

---

## Multi-Project Structure

| Resource | Project variable | Actual project |
|---|---|---|
| Secret Manager | `project_id` | `tefde-gcp-fastoss-dev-gke` |
| GCS bucket | `project_id` | `tefde-gcp-fastoss-dev-gke` |
| Artifact Registry | `project_id` | `tefde-gcp-fastoss-dev-gke` |
| Cloud Run Jobs + UI Service | `project_id` | `tefde-gcp-fastoss-dev-gke` |
| BigQuery dataset + tables | `reporting_project_id` | `tefde-gcp-fastoss-dev` |
| Service account *(external)* | — | `tefde-gcp-resvadm-prod-backend` (TEF IAM Team) |
| Shared VPC + connector *(external)* | — | `tefde-gcp-network-shared-ic-1` (TEF Networking Team) |

---

## Variables Reference

| Variable | Default | Required | Description |
|---|---|---|---|
| `project_id` | — | yes | Cloud Run / infrastructure project |
| `reporting_project_id` | — | yes | BigQuery reporting project |
| `region` | `europe-west3` | no | GCP region (also used for Secret Manager replication) |
| `dataset_id` | `devops_reports` | no | BigQuery dataset name |
| `reports_gcs_bucket` | — | yes | GCS bucket name for CSV outputs |
| `gitlab_token_secret_id` | `gitlab-token` | no | Secret Manager secret ID for GitLab PAT |
| `cloud_run_sa_email` | — | yes | Full email of the SA provided by the TEF IAM Team |
| `container_image` | — | yes | Full Docker image URI for Cloud Run Jobs |
| `ui_container_image` | — | yes | Full Docker image URI for the UI Cloud Run Service |
| `gitlab_base_url` | `https://dot-portal.de.pri.o2.com/gitlab` | no | GitLab instance URL |
| `gitlab_subgroup` | `ndl_core` | no | Subgroup scanned by reports |
| `vpc_connector_name` | `fastoss-dev-gke-connector` | no | Name of the VPC Access Connector provisioned by the Networking Team |
| `artifact_registry_repo_id` | `devops-reports` | no | Artifact Registry repository ID |
| `bq_scan_project_id` | — | yes | BigQuery project scanned by the orphan datasets report |
| `ui_invoker_member` | `allAuthenticatedUsers` | no | IAM member allowed to invoke the UI (use `domain:yourcompany.com`) |

---

## Deploy

```bash
terraform init
terraform plan
terraform apply
```

---

## Post-Apply Manual Steps

### 1. Load the GitLab PAT

```bash
gcloud secrets versions add gitlab-token \
  --project=tefde-gcp-fastoss-dev-gke \
  --data-file=- <<< "YOUR_GITLAB_PAT"
```

### 2. Build and push the Docker images

Images are built automatically by the GitLab CI pipeline. To build manually:

```bash
SHA=$(git rev-parse --short HEAD)

docker build -f ../Dockerfile.python \
  -t europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports:$SHA ..
docker push \
  europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports:$SHA

docker build -f ../ui/Dockerfile \
  -t europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports-ui:$SHA ../ui
docker push \
  europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports-ui:$SHA
```

---

## Service Account

The single service account `devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com`
is **created and managed by the TEF IAM Team**. It is not provisioned by this Terraform workspace.

All `google_*_iam_member` resources referencing this SA are commented out in the Terraform files.
The TEF IAM Team applies the grants listed in `../IAM_admin_instructions.md`.

The Terraform deployer identity must hold `roles/iam.serviceAccountUser` on this SA
(Grant #10 in `IAM_admin_instructions.md`) before running `terraform apply`.

---

## Networking

Network connectivity is **provisioned and managed by the TEF Networking Team**.
This workspace does not create a VPC, subnet, connector, or firewall rules —
`networking.tf` only reads the existing VPC Access Connector via a data source.

| Resource | Name | Project |
|---|---|---|
| Shared VPC network | `tefde-gcp-network-shared-ic-1-vpc-devlowapp` | `tefde-gcp-network-shared-ic-1` (host) |
| Subnet | `s-shared-ew3-devlow-fastoss-dev-gke-connect-1` (europe-west3) | `tefde-gcp-network-shared-ic-1` (host) |
| VPC Access Connector | `fastoss-dev-gke-connector` (europe-west3) | `tefde-gcp-fastoss-dev-gke` |

If the Networking Team renames or recreates the connector, update `vpc_connector_name`
in `terraform.tfvars` to match.
