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
#     --iam-account=devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com \
#     --project=tefde-gcp-fastoss-dev-gke
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
# Networking — VPC, subnet, VPC Access Connector, firewall rules
# ---------------------------------------------------------------------------
# IP CIDR of the private network hosting dot-portal.de.pri.o2.com.
# Used to scope the egress firewall rule that allows HTTPS to GitLab.
# Ask your network team for the correct range, e.g. "10.100.0.0/16".
gitlab_network_cidr = "REPLACE_WITH_GITLAB_NETWORK_CIDR"

# Optional overrides — defaults shown, change only if they conflict with
# existing subnets in your VPC address space.
# vpc_network_name      = "devops-reports-vpc"
# connector_subnet_cidr = "10.8.0.0/28"
