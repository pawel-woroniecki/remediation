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
  location                    = var.region
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
  location   = var.region
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
    { name = "project_name", type = "STRING" },
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
    { name = "severity", type = "STRING" },
    { name = "gcs_report_path", type = "STRING" }
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

# ---------------------------------------------------------------------------
# Looker Studio view — per-repository env-drift summary with report link
# ---------------------------------------------------------------------------
# Connect to Looker Studio as a BigQuery data source:
#   Looker Studio → Add data → BigQuery → Custom query → SELECT * FROM devops_reports.env_drift_summary
# Set the report_url field type to URL in the data source settings.
resource "google_bigquery_table" "env_drift_summary" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "env_drift_summary"
  deletion_protection = false

  view {
    query = <<-EOT
      SELECT
        e.execution_id,
        COALESCE(e.environment, 'prod')                               AS environment,
        f.product                                                     AS repository,
        DATE(e.execution_ts)                                          AS execution_date,
        e.execution_ts,
        ROW_NUMBER() OVER (
          PARTITION BY f.product, COALESCE(e.environment, 'prod'), DATE(e.execution_ts)
          ORDER BY e.execution_ts
        )                                                             AS run_number,
        COUNTIF(f.component_type = 'bigquery')                        AS bq_findings,
        COUNTIF(f.component_type = 'gcs')                             AS gcs_findings,
        ANY_VALUE(f.gcs_report_path)                                  AS report_url
      FROM `${var.reporting_project_id}.devops_reports.executions` e
      JOIN `${var.reporting_project_id}.devops_reports.env_drift_findings` f
        USING (execution_id)
      WHERE e.report_type = 'env_drift'
      GROUP BY
        e.execution_id, COALESCE(e.environment, 'prod'), f.product, e.execution_ts
    EOT
    use_legacy_sql = false
  }
}

# ---------------------------------------------------------------------------
# Looker Studio view — management dashboard (red/green repo health grid)
# ---------------------------------------------------------------------------
# Connect to Looker Studio as a BigQuery data source:
#   Looker Studio → Add data → BigQuery → devops_reports.management_dashboard
# Create calculated fields IF(metric=0,"●",TEXT(metric)) per column, then
# apply conditional formatting: "●" → green font, otherwise → red bold font.
resource "google_bigquery_table" "management_dashboard" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "management_dashboard"
  deletion_protection = false

  view {
    query = <<-EOT
      WITH env_per_exec AS (
        SELECT
          e.execution_id,
          COALESCE(e.project_name, f.product)    AS repo,
          DATE(e.execution_ts)                   AS run_date,
          e.execution_ts,
          COUNTIF(f.component_type = 'bigquery') AS bq_findings,
          COUNTIF(f.component_type = 'gcs')      AS gcs_findings
        FROM `${var.reporting_project_id}.devops_reports.executions` e
        LEFT JOIN `${var.reporting_project_id}.devops_reports.env_drift_findings` f
          USING (execution_id)
        WHERE e.report_type = 'env_drift'
          AND e.status = 'success'
          AND COALESCE(e.environment, 'prod') = 'prod'
          AND COALESCE(e.project_name, f.product) IS NOT NULL
        GROUP BY e.execution_id, COALESCE(e.project_name, f.product), DATE(e.execution_ts), e.execution_ts
      ),

      env_with_run AS (
        SELECT
          *,
          ROW_NUMBER() OVER (
            PARTITION BY repo, run_date
            ORDER BY execution_ts
          ) AS run_number
        FROM env_per_exec
      ),

      commit_latest AS (
        SELECT
          k.repo,
          k.run_date,
          SUM(CASE
            WHEN k.status = 'ok'
              AND (
                (REGEXP_EXTRACT(k.right_branch, r'origin/(.+)') = 'production'
                 AND REGEXP_EXTRACT(k.left_branch,  r'origin/(.+)') IN ('master','test'))
                OR
                (REGEXP_EXTRACT(k.right_branch, r'origin/(.+)') = 'test'
                 AND REGEXP_EXTRACT(k.left_branch,  r'origin/(.+)') = 'master')
              )
            THEN COALESCE(k.unique_commits, 0)
            ELSE 0
          END) AS red_flags
        FROM `${var.reporting_project_id}.devops_reports.branch_drift_kpis` k
        JOIN `${var.reporting_project_id}.devops_reports.executions` e
          USING (execution_id)
        WHERE e.report_type = 'commit_drift'
          AND k.drift_type = 'commit'
        GROUP BY k.repo, k.run_date, k.execution_id, e.execution_ts
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY k.repo, k.run_date ORDER BY e.execution_ts DESC
        ) = 1
      ),

      file_latest AS (
        SELECT
          k.repo,
          k.run_date,
          SUM(CASE WHEN k.status = 'ok' THEN COALESCE(k.unique_files, 0) ELSE 0 END)
            AS file_drift
        FROM `${var.reporting_project_id}.devops_reports.branch_drift_kpis` k
        JOIN `${var.reporting_project_id}.devops_reports.executions` e
          USING (execution_id)
        WHERE e.report_type = 'file_drift'
          AND k.drift_type = 'content'
        GROUP BY k.repo, k.run_date, k.execution_id, e.execution_ts
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY k.repo, k.run_date ORDER BY e.execution_ts DESC
        ) = 1
      )

      SELECT
        COALESCE(env.repo, c.repo, f.repo)             AS repository,
        COALESCE(env.run_date, c.run_date, f.run_date) AS run_date,
        COALESCE(env.run_number, 1)                    AS run_number,
        COALESCE(env.bq_findings,  0)                  AS bq_findings,
        COALESCE(env.gcs_findings, 0)                  AS gcs_findings,
        COALESCE(c.red_flags,      0)                  AS red_flags,
        COALESCE(f.file_drift,     0)                  AS file_drift,
        CASE
          WHEN COALESCE(env.bq_findings, 0)
             + COALESCE(env.gcs_findings, 0)
             + COALESCE(c.red_flags, 0)
             + COALESCE(f.file_drift, 0) = 0
          THEN 'All clear'
          ELSE 'Has findings'
        END                                            AS status
      FROM env_with_run env
      FULL OUTER JOIN commit_latest c
        ON env.repo = c.repo AND env.run_date = c.run_date
      FULL OUTER JOIN file_latest f
        ON COALESCE(env.repo, c.repo) = f.repo
       AND COALESCE(env.run_date, c.run_date) = f.run_date
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

