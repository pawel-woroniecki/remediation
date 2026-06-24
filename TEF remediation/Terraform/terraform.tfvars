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
# Image pushes from CI/CD use the devops-reports-runner SA (see artifact_registry.tf).
# Generate a key for that SA and store it as GCP_SA_KEY in GitLab CI variables:
#   gcloud iam service-accounts keys create runner-key.json \
#     --iam-account=devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com \
#     --project=tefde-gcp-resvadm-prod-backend
artifact_registry_repo_id = "devops-reports"

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
ui_invoker_member = "domain:telefonica.de"

# ---------------------------------------------------------------------------
# Service account
# ---------------------------------------------------------------------------
# The SA is created by the IAM team — do not modify this value.
cloud_run_sa_email = "devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com"

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
# Networking — Shared VPC connectivity (provisioned by the TEF Networking Team)
# ---------------------------------------------------------------------------
# VPC Access Connector created by the Networking Team in europe-west3,
# attached to the Shared VPC tefde-gcp-network-shared-ic-1-vpc-devlowapp
# (host project: tefde-gcp-network-shared-ic-1). Looked up via a data
# source — this workspace does not create or manage the VPC, subnet,
# connector, or firewall rules.
vpc_connector_name = "fastoss-dev-gke-connector"
