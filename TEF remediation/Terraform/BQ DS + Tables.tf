# ---------------------------------------------------------------------------
# Secret Manager — GitLab PAT
# ---------------------------------------------------------------------------
# This resource creates the secret container only.
# Load the actual token value after apply:
#   gcloud secrets versions add gitlab-token --data-file=- <<< "YOUR_PAT"
resource "google_secret_manager_secret" "gitlab_token" {
  project   = var.project_id
  secret_id = var.gitlab_token_secret_id

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.secretmanager]
}

# NOTE: IAM binding managed by the TEF IAM Team.
# The service account devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com
# is owned by that team. This resource is kept here for documentation purposes only.
# Do not apply if the TEF IAM Team manages permissions directly to avoid conflicts.
# resource "google_secret_manager_secret_iam_member" "gitlab_token_accessor" {
#   project   = var.project_id
#   secret_id = google_secret_manager_secret.gitlab_token.secret_id
#   role      = "roles/secretmanager.secretAccessor"
#   member    = "serviceAccount:${var.cloud_run_sa_email}"
# }

# ---------------------------------------------------------------------------
# GCS bucket — report CSV outputs
# ---------------------------------------------------------------------------
resource "google_storage_bucket" "devops_reports" {
  name                        = var.reports_gcs_bucket
  project                     = var.project_id
  location                    = "EU"
  uniform_bucket_level_access = true

  lifecycle_rule {
    action { type = "Delete" }
    condition { age = 365 }
  }

  depends_on = [google_project_service.storage_gke]
}

# NOTE: IAM binding managed by the TEF IAM Team.
# The service account devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com
# is owned by that team. This resource is kept here for documentation purposes only.
# Do not apply if the TEF IAM Team manages permissions directly to avoid conflicts.
# resource "google_storage_bucket_iam_member" "reports_runner_gcs_writer" {
#   bucket = google_storage_bucket.devops_reports.name
#   role   = "roles/storage.objectCreator"
#   member = "serviceAccount:${var.cloud_run_sa_email}"
# }

# ---------------------------------------------------------------------------
# BigQuery IAM — dataset-level write + project-level job execution
# ---------------------------------------------------------------------------
# NOTE: IAM binding managed by the TEF IAM Team.
# The service account devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com
# is owned by that team. This resource is kept here for documentation purposes only.
# Do not apply if the TEF IAM Team manages permissions directly to avoid conflicts.
# resource "google_bigquery_dataset_iam_member" "reports_runner_editor" {
#   project    = var.reporting_project_id
#   dataset_id = google_bigquery_dataset.devops_reports.dataset_id
#   role       = "roles/bigquery.dataEditor"
#   member     = "serviceAccount:${var.cloud_run_sa_email}"
# }

# bigquery.jobUser must be granted in the project where BQ jobs are executed,
# which is the reporting project (where the dataset lives).
# NOTE: IAM binding managed by the TEF IAM Team.
# The service account devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com
# is owned by that team. This resource is kept here for documentation purposes only.
# Do not apply if the TEF IAM Team manages permissions directly to avoid conflicts.
# resource "google_project_iam_member" "reports_runner_bq_job_user" {
#   project = var.reporting_project_id
#   role    = "roles/bigquery.jobUser"
#   member  = "serviceAccount:${var.cloud_run_sa_email}"
# }

# ---------------------------------------------------------------------------
# BigQuery IAM — orphan dataset scan project
# ---------------------------------------------------------------------------
# The orphan_datasets report scans a separate BigQuery project (typically prod)
# for datasets not referenced by any repo. The runner SA needs read access there.
# NOTE: IAM binding managed by the TEF IAM Team.
# The service account devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com
# is owned by that team. This resource is kept here for documentation purposes only.
# Do not apply if the TEF IAM Team manages permissions directly to avoid conflicts.
# resource "google_project_iam_member" "reports_runner_scan_bq_viewer" {
#   project = var.bq_scan_project_id
#   role    = "roles/bigquery.metadataViewer"
#   member  = "serviceAccount:${var.cloud_run_sa_email}"
# }

# NOTE: IAM binding managed by the TEF IAM Team.
# The service account devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com
# is owned by that team. This resource is kept here for documentation purposes only.
# Do not apply if the TEF IAM Team manages permissions directly to avoid conflicts.
# resource "google_project_iam_member" "reports_runner_scan_bq_job_user" {
#   project = var.bq_scan_project_id
#   role    = "roles/bigquery.jobUser"
#   member  = "serviceAccount:${var.cloud_run_sa_email}"
# }

resource "google_bigquery_dataset" "devops_reports" {
  dataset_id = var.dataset_id
  project    = var.reporting_project_id
  location   = "EU"
  default_table_expiration_ms = 31536000000 # 365 days

  description = "Unified DevOps governance and drift reporting"

  labels = {
    domain = "devops"
    owner  = "platform"
  }

  depends_on = [
    google_project_service.bigquery,
    google_project_service.iam_reporting,
  ]
}

resource "google_bigquery_table" "executions" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "executions"
  deletion_protection = true

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED" },
    { name = "report_type", type = "STRING", mode = "REQUIRED" },
    { name = "execution_ts", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "environment", type = "STRING" },
    { name = "git_ref", type = "STRING" },
    { name = "source_mode", type = "STRING" },
    { name = "triggered_by", type = "STRING" },
    { name = "status", type = "STRING" },
    { name = "duration_seconds", type = "INT64" },
    { name = "gcs_path", type = "STRING" }
  ])

  time_partitioning {
    type  = "DAY"
    field = "execution_ts"
  }
}

resource "google_bigquery_table" "entities" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "entities"
  deletion_protection = true

  schema = jsonencode([
    { name = "entity_id", type = "STRING", mode = "REQUIRED" },
    { name = "entity_type", type = "STRING", mode = "REQUIRED" },
    { name = "name", type = "STRING", mode = "REQUIRED" },
    { name = "domain", type = "STRING" },
    { name = "owner", type = "STRING" },
    { name = "lifecycle", type = "STRING" }
  ])
}

resource "google_bigquery_table" "branch_drift_kpis" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "branch_drift_kpis"
  deletion_protection = true

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED" },
    { name = "run_date", type = "DATE" },
    { name = "repo", type = "STRING", mode = "REQUIRED" },
    { name = "left_branch", type = "STRING" },
    { name = "right_branch", type = "STRING" },
    { name = "drift_type", type = "STRING" },
    { name = "comparison_mode", type = "STRING" },
    { name = "unique_commits", type = "INT64" },
    { name = "unique_files", type = "INT64" },
    { name = "severity", type = "STRING" },
    { name = "status", type = "STRING" }
  ])

  time_partitioning {
    type  = "DAY"
    field = "run_date"
  }

  clustering = ["repo", "drift_type"]
}

resource "google_bigquery_table" "branch_drift_evidence" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "branch_drift_evidence"
  deletion_protection = true

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED" },
    { name = "run_date", type = "DATE" },
    { name = "repo", type = "STRING" },
    { name = "drift_type", type = "STRING" },
    { name = "discrepancy", type = "STRING" },
    { name = "commit_sha", type = "STRING" },
    { name = "commit_date", type = "TIMESTAMP" },
    { name = "author", type = "STRING" },
    { name = "file_path", type = "STRING" },
    { name = "change_type", type = "STRING" },
    { name = "problem_statement", type = "STRING" }
  ])

  time_partitioning {
    type  = "DAY"
    field = "run_date"
  }

  clustering = ["repo", "discrepancy"]
}

resource "google_bigquery_table" "env_drift_findings" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "env_drift_findings"
  deletion_protection = true

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED" },
    { name = "product", type = "STRING" },
    { name = "component_type", type = "STRING" },
    { name = "object_type", type = "STRING" },
    { name = "object_name", type = "STRING" },
    { name = "drift_category", type = "STRING" },
    { name = "source_hash", type = "STRING" },
    { name = "env_hash", type = "STRING" },
    { name = "severity", type = "STRING" }
  ])

  clustering = ["product", "component_type"]
}

resource "google_bigquery_table" "orphan_datasets" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "orphan_datasets"
  deletion_protection = true

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED" },
    { name = "dataset_name", type = "STRING", mode = "REQUIRED" },
    { name = "project_id", type = "STRING" },
    { name = "orphan_status", type = "STRING" },
    { name = "source_reference_found", type = "BOOL" },
    { name = "last_modified", type = "TIMESTAMP" },
    { name = "table_count", type = "INT64" },
    { name = "owner", type = "STRING" },
    { name = "risk_score", type = "INT64" }
  ])

  clustering = ["orphan_status"]
}

# ---------------------------------------------------------------------------
# Looker Studio / Cloud Monitoring view — daily success/failure rates
# ---------------------------------------------------------------------------
# Connect this view directly to Looker Studio as a BigQuery data source:
#   Looker Studio → Create → Data Source → BigQuery → Custom Query
#   or select devops_reports.execution_daily_summary
resource "google_bigquery_table" "execution_daily_summary" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "execution_daily_summary"
  deletion_protection = false

  view {
    query = <<-EOT
      SELECT
        DATE(execution_ts)                                     AS execution_date,
        report_type,
        COUNTIF(status = 'success')                           AS success_count,
        COUNTIF(status = 'failed')                            AS failure_count,
        COUNT(*)                                              AS total_count,
        SAFE_DIVIDE(COUNTIF(status = 'success'), COUNT(*))   AS success_rate
      FROM `${var.reporting_project_id}.devops_reports.executions`
      GROUP BY 1, 2
    EOT
    use_legacy_sql = false
  }
}

resource "google_bigquery_table" "orphan_dataset_objects" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "orphan_dataset_objects"
  deletion_protection = true

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED" },
    { name = "dataset_name", type = "STRING", mode = "REQUIRED" },
    { name = "object_type", type = "STRING" },
    { name = "object_name", type = "STRING" },
    { name = "last_modified", type = "TIMESTAMP" },
    { name = "row_count", type = "INT64" },
    { name = "storage_mb", type = "FLOAT64" }
  ])
}

