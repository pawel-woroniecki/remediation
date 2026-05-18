# ---------------------------------------------------------------------------
# Project IDs
# ---------------------------------------------------------------------------
project_id           = "tefde-gcp-fastoss-dev-gke"   # Cloud Run, GCS, Secret Manager, Service Account
reporting_project_id = "tefde-gcp-fastoss-dev"        # BigQuery dataset and tables

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
region              = "europe-west3"
dataset_id          = "devops_reports"
reports_gcs_bucket  = "tefde-gcp-fastoss-dev-gcs-devops-reports"

# ---------------------------------------------------------------------------
# Artifact Registry
# ---------------------------------------------------------------------------
artifact_registry_repo_id = "devops-reports"
cicd_sa_email             = "YOUR_GITLAB_RUNNER_SA@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com"

# ---------------------------------------------------------------------------
# Container images
# ---------------------------------------------------------------------------
# Set these after the images are built and pushed to Artifact Registry.
container_image    = "europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports:latest"
ui_container_image = "europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports-ui:latest"

# ---------------------------------------------------------------------------
# Orphan datasets — BigQuery scan project
# ---------------------------------------------------------------------------
# The project whose BigQuery datasets are scanned for orphans.
# This is typically a production data project, separate from the reporting project.
bq_scan_project_id = "tefde-gcp-fastoss-prod"

# ---------------------------------------------------------------------------
# UI access control
# ---------------------------------------------------------------------------
# Restrict to your Google Workspace domain (recommended):
#   ui_invoker_member = "domain:yourcompany.com"
# Or a specific Google Group:
#   ui_invoker_member = "group:devops-team@yourcompany.com"
ui_invoker_member = "allAuthenticatedUsers"

# ---------------------------------------------------------------------------
# Service account
# ---------------------------------------------------------------------------
cloud_run_sa_name = "devops-reports-runner"

# ---------------------------------------------------------------------------
# Secret Manager
# ---------------------------------------------------------------------------
gitlab_token_secret_id = "gitlab-token"

# ---------------------------------------------------------------------------
# GitLab
# ---------------------------------------------------------------------------
gitlab_base_url = "https://dot-portal.de.pri.o2.com/gitlab"
gitlab_subgroup = "ndl_core"

# ---------------------------------------------------------------------------
# VPC (optional — uncomment if GitLab is on a private network)
# ---------------------------------------------------------------------------
# vpc_connector = "projects/tefde-gcp-fastoss-dev-gke/locations/europe-west3/connectors/YOUR_CONNECTOR"
