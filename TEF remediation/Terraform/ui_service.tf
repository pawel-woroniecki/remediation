# ---------------------------------------------------------------------------
# Service Account — UI Cloud Run Service
# ---------------------------------------------------------------------------
resource "google_service_account" "reports_ui" {
  project      = var.project_id
  account_id   = "devops-reports-ui"
  display_name = "DevOps Reports UI"
  description  = "Runtime identity for the DevOps Reports web UI Cloud Run Service."

  depends_on = [
    google_project_service.iam_gke,
    google_project_service.cloudresourcemanager_gke,
  ]
}

# Trigger Cloud Run Jobs and read execution status
resource "google_project_iam_member" "reports_ui_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.reports_ui.email}"
}

# Read BigQuery executions table
resource "google_bigquery_dataset_iam_member" "reports_ui_bq_viewer" {
  project    = var.reporting_project_id
  dataset_id = google_bigquery_dataset.devops_reports.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.reports_ui.email}"
}

resource "google_project_iam_member" "reports_ui_bq_job_user" {
  project = var.reporting_project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.reports_ui.email}"
}

# ---------------------------------------------------------------------------
# Cloud Run Service — UI
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "reports_ui" {
  name     = "devops-reports-ui"
  location = var.region
  project  = var.project_id

  depends_on = [google_project_service.run]

  template {
    service_account = google_service_account.reports_ui.email

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
  value       = google_service_account.reports_ui.email
  description = "Service account email used by the UI Cloud Run Service."
}
