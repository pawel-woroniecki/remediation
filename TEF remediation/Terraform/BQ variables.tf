terraform {
  required_version = ">= 1.4.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

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

variable "cloud_run_sa_name" {
  type        = string
  default     = "devops-reports-runner"
  description = "Account ID for the Cloud Run Jobs service account (created by Terraform)."
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

variable "vpc_connector" {
  type        = string
  default     = null
  description = "Optional VPC Access Connector resource name. Required if GitLab is on a private network."
}

variable "artifact_registry_repo_id" {
  type        = string
  default     = "devops-reports"
  description = "Artifact Registry repository ID for the devops-reports Docker image."
}

variable "cicd_sa_email" {
  type        = string
  description = "Service account email used by the CI/CD pipeline (e.g. GitLab Runner) to push Docker images to Artifact Registry."
}