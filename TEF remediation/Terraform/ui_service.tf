# ---------------------------------------------------------------------------
# UI permissions — granted to the shared devops-reports-runner SA
#
# NOTE: granting run.developer to the runner SA means the identity that
# executes inside Cloud Run Jobs can also trigger new jobs. This is an
# accepted trade-off in exchange for reducing to a single service account.
# ---------------------------------------------------------------------------

# Trigger Cloud Run Jobs and read execution status (needed by the UI backend)
# NOTE: IAM binding managed by the TEF IAM Team.
# The service account devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com
# is owned by that team. This resource is kept here for documentation purposes only.
# Do not apply if the TEF IAM Team manages permissions directly to avoid conflicts.
# resource "google_project_iam_member" "reports_runner_run_developer" {
#   project = var.project_id
#   role    = "roles/run.developer"
#   member  = "serviceAccount:${var.cloud_run_sa_email}"
# }

# BigQuery dataViewer and jobUser on the reporting project are already granted
# to devops-reports-runner via reports_runner_editor (dataEditor) and
# reports_runner_bq_job_user in BQ DS + Tables.tf — no additional bindings needed.

# ---------------------------------------------------------------------------
# Cloud Run Service — UI
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "reports_ui" {
  name     = "devops-reports-ui"
  location = var.region
  project  = var.project_id

  depends_on = [google_project_service.run]

  template {
    service_account = var.cloud_run_sa_email

    containers {
      image = var.ui_container_image

      env {
        name  = "GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "REPORTING_PROJECT"
        value = var.reporting_project_id
      }
      env {
        name  = "REGION"
        value = var.region
      }
      env {
        name  = "GCS_BUCKET"
        value = var.reports_gcs_bucket
      }
      env {
        name  = "BQ_SCAN_PROJECT"
        value = var.bq_scan_project_id
      }

      resources {
        limits = {
          memory = "512Mi"
          cpu    = "1"
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
# Currently open to all authenticated Google accounts.
# To restrict to your organisation, replace "allAuthenticatedUsers" with:
#   "domain:yourcompany.com"           — everyone in a Google Workspace domain
#   "group:team@yourcompany.com"       — a specific Google Group
#   "user:alice@yourcompany.com"       — individual users
# For proper browser SSO without sharing the URL publicly, add Google IAP
# via an HTTPS load balancer (separate Terraform module).
resource "google_cloud_run_v2_service_iam_member" "ui_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.reports_ui.name
  role     = "roles/run.invoker"
  member   = var.ui_invoker_member
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
output "ui_url" {
  value       = google_cloud_run_v2_service.reports_ui.uri
  description = "URL of the DevOps Reports web UI."
}

output "ui_sa_email" {
  value       = var.cloud_run_sa_email
  description = "Service account email used by the UI Cloud Run Service (shared with Cloud Run Jobs)."
}
