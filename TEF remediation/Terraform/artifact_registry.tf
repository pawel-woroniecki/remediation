# ---------------------------------------------------------------------------
# Artifact Registry — Docker repository for the devops-reports image
# ---------------------------------------------------------------------------
resource "google_artifact_registry_repository" "devops_reports" {
  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_registry_repo_id
  format        = "DOCKER"
  description   = "Docker images for devops-reports Cloud Run Jobs."
}

# Grant the Cloud Run Jobs service account permission to pull images.
# NOTE: IAM binding managed by the TEF IAM Team.
# The service account devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com
# is owned by that team. This resource is kept here for documentation purposes only.
# Do not apply if the TEF IAM Team manages permissions directly to avoid conflicts.
# resource "google_artifact_registry_repository_iam_member" "reports_runner_reader" {
#   project    = var.project_id
#   location   = var.region
#   repository = google_artifact_registry_repository.devops_reports.name
#   role       = "roles/artifactregistry.reader"
#   member     = "serviceAccount:${var.cloud_run_sa_email}"
# }

# Grant the Cloud Run Jobs service account permission to push images from CI/CD.
# NOTE: IAM binding managed by the TEF IAM Team.
# The service account devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com
# is owned by that team. This resource is kept here for documentation purposes only.
# Do not apply if the TEF IAM Team manages permissions directly to avoid conflicts.
# resource "google_artifact_registry_repository_iam_member" "cicd_writer" {
#   project    = var.project_id
#   location   = var.region
#   repository = google_artifact_registry_repository.devops_reports.name
#   role       = "roles/artifactregistry.writer"
#   member     = "serviceAccount:${var.cloud_run_sa_email}"
# }

# ---------------------------------------------------------------------------
# Output — use this as the base path for container_image in terraform.tfvars
# ---------------------------------------------------------------------------
output "artifact_registry_base_url" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_registry_repo_id}"
  description = "Base URL for Docker images. Append /<image-name>:<tag> to get the full image URI."
}
