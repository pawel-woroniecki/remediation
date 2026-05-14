# ---------------------------------------------------------------------------
# Looker — read-only service account for BigQuery access
# ---------------------------------------------------------------------------
# Configure this SA in Looker Admin → Database → Connections → BigQuery.

resource "google_service_account" "looker_bq_reader" {
  project      = var.reporting_project_id
  account_id   = "looker-bq-reader"
  display_name = "Looker BigQuery Reader"
  description  = "Read-only access to devops_reports dataset for Looker dashboards."
}

# Read data from the devops_reports dataset.
resource "google_bigquery_dataset_iam_member" "looker_viewer" {
  project    = var.reporting_project_id
  dataset_id = google_bigquery_dataset.devops_reports.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.looker_bq_reader.email}"
}

# Execute BigQuery jobs (required by the BQ client to run queries).
resource "google_project_iam_member" "looker_bq_job_user" {
  project = var.reporting_project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.looker_bq_reader.email}"
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
output "looker_sa_email" {
  value       = google_service_account.looker_bq_reader.email
  description = "Enter this service account email in Looker Admin → Connections → BigQuery."
}
