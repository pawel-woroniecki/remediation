variable "project_id" {
  type        = string
  description = "GCP project ID for Cloud Run Jobs, GCS bucket, Secret Manager, and the service account (tefde-gcp-fastoss-dev-gke)."
}

variable "reporting_project_id" {
  type        = string
  description = "GCP project ID where BigQuery dataset and tables are created (tefde-gcp-fastoss-dev)."
}

variable "region" {
  type        = string
  default     = "europe-west3"
}

variable "dataset_id" {
  type        = string
  default     = "devops_reports"
}

variable "reports_gcs_bucket" {
  type        = string
  description = "Name of the GCS bucket used to store report CSV outputs."
}

variable "gitlab_token_secret_id" {
  type        = string
  default     = "gitlab-token"
  description = "Secret Manager secret ID that stores the GitLab PAT (read_api + read_repository scopes)."
}

variable "cloud_run_sa_email" {
  type        = string
  description = "Full email address of the Cloud Run service account created by the IAM team, e.g. devops-reports-runner@PROJECT.iam.gserviceaccount.com"
}

variable "container_image" {
  type        = string
  description = "Full URI of the Docker image to run in all Cloud Run Jobs, e.g. europe-west3-docker.pkg.dev/PROJECT/REPO/devops-reports:latest"
}

variable "gitlab_base_url" {
  type        = string
  default     = "https://dot-portal.de.pri.o2.com/gitlab"
  description = "Base URL of the GitLab instance."
}

variable "gitlab_subgroup" {
  type        = string
  default     = "ndl_core"
  description = "GitLab subgroup name scanned by env_drift, commit_drift, and file_drift reports."
}

variable "vpc_connector_name" {
  type        = string
  default     = "fastoss-dev-gke-connector"
  description = "Name of the VPC Access Connector provisioned by the TEF Networking Team in europe-west3, attached to the Shared VPC tefde-gcp-network-shared-ic-1-vpc-devlowapp. Looked up via a data source — not created by this workspace."
}

variable "artifact_registry_repo_id" {
  type        = string
  default     = "devops-reports"
  description = "Artifact Registry repository ID for the devops-reports Docker image."
}

variable "ui_container_image" {
  type        = string
  description = "Full URI of the Docker image for the DevOps Reports web UI Cloud Run Service, e.g. europe-west3-docker.pkg.dev/PROJECT/REPO/devops-reports-ui:latest"
}

variable "bq_scan_project_id" {
  type        = string
  description = "GCP project ID that contains the BigQuery datasets scanned by the orphan_datasets report. Often a production project separate from the reporting project."
}

variable "ui_invoker_member" {
  type        = string
  default     = "allAuthenticatedUsers"
  description = "IAM member string allowed to invoke the UI Cloud Run Service. Use 'domain:yourcompany.com' to restrict to a Google Workspace domain, or 'group:team@yourcompany.com' for a specific group."
}