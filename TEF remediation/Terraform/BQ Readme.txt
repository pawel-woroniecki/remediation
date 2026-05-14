# Terraform — DevOps Reports Infrastructure

Provisions all GCP infrastructure for the devops-reports framework across two projects.

---

## Files

| File | Contents |
|---|---|
| `BQ variables.tf` | Terraform provider, required providers, and all input variables |
| `BQ DS + Tables.tf` | Service account, Secret Manager, GCS bucket, BigQuery dataset + 7 tables, IAM bindings |
| `Cloud Run Jobs.tf` | 4 Cloud Run Job resources (one per report type) |
| `artifact_registry.tf` | Artifact Registry Docker repository + pull/push IAM |
| `apis.tf` | GCP API enablement for both projects |
| `looker.tf` | Looker read-only service account + BigQuery IAM |
| `terraform.tfvars` | Variable values — fill in before running |

---

## Two-Project Structure

| Resource | Project variable | Actual project |
|---|---|---|
| Service account | `project_id` | `tefde-gcp-fastoss-dev-gke` |
| Secret Manager | `project_id` | `tefde-gcp-fastoss-dev-gke` |
| GCS bucket | `project_id` | `tefde-gcp-fastoss-dev-gke` |
| Artifact Registry | `project_id` | `tefde-gcp-fastoss-dev-gke` |
| Cloud Run Jobs | `project_id` | `tefde-gcp-fastoss-dev-gke` |
| BigQuery dataset + tables | `reporting_project_id` | `tefde-gcp-fastoss-dev` |
| Looker SA | `reporting_project_id` | `tefde-gcp-fastoss-dev` |

---

## Variables Reference

| Variable | Default | Required | Description |
|---|---|---|---|
| `project_id` | — | yes | Cloud Run / infrastructure project |
| `reporting_project_id` | — | yes | BigQuery reporting project |
| `region` | `europe-west3` | no | GCP region |
| `dataset_id` | `devops_reports` | no | BigQuery dataset name |
| `reports_gcs_bucket` | — | yes | GCS bucket name for CSV outputs |
| `gitlab_token_secret_id` | `gitlab-token` | no | Secret Manager secret ID for GitLab PAT |
| `cloud_run_sa_name` | `devops-reports-runner` | no | Service account account-id |
| `container_image` | — | yes | Full Docker image URI |
| `gitlab_base_url` | `https://dot-portal.de.pri.o2.com/gitlab` | no | GitLab instance URL |
| `gitlab_subgroup` | `ndl_core` | no | Subgroup scanned by reports |
| `vpc_connector` | `null` | no | VPC connector (if GitLab is private) |
| `artifact_registry_repo_id` | `devops-reports` | no | Artifact Registry repository ID |
| `cicd_sa_email` | — | yes | GitLab Runner SA that pushes Docker images |

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

### 2. Build and push the Docker image

```bash
docker build -f ../Dockerfile.python \
  -t europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports:latest ..

docker push \
  europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports:latest
```

### 3. Create the Looker service account key

```bash
gcloud iam service-accounts keys create looker-bq-reader-key.json \
  --iam-account=looker-bq-reader@tefde-gcp-fastoss-dev.iam.gserviceaccount.com \
  --project=tefde-gcp-fastoss-dev
```

Upload `looker-bq-reader-key.json` to **Looker Admin → Connections → BigQuery**.
Delete the local key file after uploading.

---

## Service Accounts Created

| SA | Project | Purpose |
|---|---|---|
| `devops-reports-runner` | `tefde-gcp-fastoss-dev-gke` | Cloud Run Jobs runtime identity |
| `looker-bq-reader` | `tefde-gcp-fastoss-dev` | Looker BigQuery read access |
