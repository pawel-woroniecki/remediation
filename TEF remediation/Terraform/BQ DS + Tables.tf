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
    { name = "gcs_path", type = "STRING" },
    { name = "repos_total", type = "INT64" },
    { name = "repos_launched", type = "INT64" },
    { name = "repos_success", type = "INT64" },
    { name = "repos_failed", type = "INT64" }
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

# ---------------------------------------------------------------------------
# Looker Studio view — commit staleness per repo × drift direction
# ---------------------------------------------------------------------------
# Shows, for the most recent run, how old the oldest unmerged commit is in
# each drift direction. Use days_oldest_waiting to surface stale commits that
# have been waiting to merge for weeks or months.
resource "google_bigquery_table" "branch_drift_staleness" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "branch_drift_staleness"
  deletion_protection = false

  view {
    query = <<-EOT
      WITH latest_run AS (
        SELECT repo, discrepancy, MAX(run_date) AS run_date
        FROM `${var.reporting_project_id}.devops_reports.branch_drift_evidence`
        WHERE drift_type = 'commit'
        GROUP BY repo, discrepancy
      )
      SELECT
        e.repo,
        e.discrepancy                                             AS drift_direction,
        l.run_date                                                AS snapshot_date,
        COUNT(DISTINCT e.commit_sha)                             AS commits_waiting,
        MIN(e.commit_date)                                       AS oldest_commit_date,
        MAX(e.commit_date)                                       AS newest_commit_date,
        DATE_DIFF(
          l.run_date,
          DATE(MIN(e.commit_date), 'Europe/Berlin'),
          DAY
        )                                                        AS days_oldest_waiting
      FROM `${var.reporting_project_id}.devops_reports.branch_drift_evidence` e
      JOIN latest_run l
        ON  e.repo        = l.repo
        AND e.discrepancy = l.discrepancy
        AND e.run_date    = l.run_date
      WHERE e.drift_type = 'commit'
      GROUP BY e.repo, e.discrepancy, l.run_date
    EOT
    use_legacy_sql = false
  }
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
      WHERE NOT (report_type = 'env_drift' AND project_name = '_job_summary')
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
      WITH agg AS (
        SELECT
          e.execution_id,
          COALESCE(e.environment, 'prod')        AS environment,
          f.product                              AS repository,
          DATE(e.execution_ts)                   AS execution_date,
          e.execution_ts,
          COUNTIF(f.component_type = 'bigquery') AS bq_findings,
          COUNTIF(f.component_type = 'gcs')      AS gcs_findings,
          ANY_VALUE(f.gcs_report_path)           AS report_url
        FROM `${var.reporting_project_id}.devops_reports.executions` e
        JOIN `${var.reporting_project_id}.devops_reports.env_drift_findings` f
          USING (execution_id)
        WHERE e.report_type = 'env_drift'
        GROUP BY
          e.execution_id, COALESCE(e.environment, 'prod'), f.product, e.execution_ts
      )
      SELECT
        execution_id,
        environment,
        repository,
        execution_date,
        execution_ts,
        ROW_NUMBER() OVER (
          PARTITION BY repository, environment, execution_date
          ORDER BY execution_ts
        )                AS run_number,
        bq_findings,
        gcs_findings,
        report_url
      FROM agg
    EOT
    use_legacy_sql = false
  }
}

# ---------------------------------------------------------------------------
# Looker Studio view — env_drift job-level run summary
# ---------------------------------------------------------------------------
# One row per Cloud Run job execution (project_name = '_job_summary').
# Shows overall status (success / success_with_warnings / failed) plus
# repo counts so the dashboard can display how many repos were processed.
resource "google_bigquery_table" "env_drift_job_summary" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "env_drift_job_summary"
  deletion_protection = false

  view {
    query = <<-EOT
      SELECT
        execution_id,
        execution_ts,
        COALESCE(environment, 'prod')            AS environment,
        git_ref,
        triggered_by,
        status,
        COALESCE(repos_total,    0)              AS repos_total,
        COALESCE(repos_launched, 0)              AS repos_launched,
        COALESCE(repos_success,  0)              AS repos_success,
        COALESCE(repos_failed,   0)              AS repos_failed,
        COALESCE(repos_total, 0)
          - COALESCE(repos_launched, 0)          AS repos_skipped,
        duration_seconds
      FROM `${var.reporting_project_id}.devops_reports.executions`
      WHERE report_type  = 'env_drift'
        AND project_name = '_job_summary'
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY COALESCE(environment, 'prod')
        ORDER BY execution_ts DESC
      ) = 1
    EOT
    use_legacy_sql = false
  }
}

# ---------------------------------------------------------------------------
# Looker Studio view — commit_drift job-level run summary
# ---------------------------------------------------------------------------
# One row per Cloud Run job execution of commit_drift.
# Derives per-run repo counts from branch_drift_kpis (drift_type='commit')
# so the dashboard can show repos_processed, repos_with_drift, severity counts.
resource "google_bigquery_table" "commit_drift_job_summary" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "commit_drift_job_summary"
  deletion_protection = false

  view {
    query = <<-EOT
      SELECT
        e.execution_id,
        e.execution_ts,
        e.triggered_by,
        e.status,
        e.duration_seconds,
        COUNT(DISTINCT k.repo)                                                                     AS repos_processed,
        COUNT(DISTINCT k.repo) - COUNT(DISTINCT IF(k.status != 'ok', k.repo, NULL))               AS repos_ok,
        COUNT(DISTINCT IF(k.status = 'missing_branch', k.repo, NULL))                             AS repos_missing_branch,
        COUNT(DISTINCT IF(k.severity != 'none',        k.repo, NULL))                             AS repos_with_drift,
        -- repos with any commits in a critical direction:
        --   production not in master  (left=master,  right=production)
        --   test not in master        (left=master,  right=test)
        --   production not in test    (left=test,    right=production)
        -- left_branch is the base; right_branch is the branch with extra commits
        COUNT(DISTINCT IF(
          k.unique_commits > 0 AND (
            (k.left_branch LIKE '%master%' AND k.right_branch LIKE '%production%') OR
            (k.left_branch LIKE '%master%' AND k.right_branch LIKE '%test%')       OR
            (k.left_branch LIKE '%test%'   AND k.right_branch LIKE '%production%')
          ), k.repo, NULL
        ))                                                                                          AS repos_critical_drift,
        COALESCE(SUM(k.unique_commits), 0)                                                         AS total_commits_in_drift
      FROM `${var.reporting_project_id}.devops_reports.executions` e
      LEFT JOIN `${var.reporting_project_id}.devops_reports.branch_drift_kpis` k
        USING (execution_id)
      WHERE e.report_type = 'commit_drift'
        AND (k.drift_type = 'commit' OR k.drift_type IS NULL)
        AND (k.repo IS NULL OR k.repo NOT IN (
          'central_cicd_templates', 'cloud_run_source', 'dataflow', 'dataquality_framework'
        ))
      GROUP BY 1, 2, 3, 4, 5
    EOT
    use_legacy_sql = false
  }
}

# ---------------------------------------------------------------------------
# Looker Studio view — file_drift job-level run summary
# ---------------------------------------------------------------------------
# One row per Cloud Run job execution of file_drift.
# Derives per-run repo counts from branch_drift_kpis (drift_type='content').
resource "google_bigquery_table" "file_drift_job_summary" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "file_drift_job_summary"
  deletion_protection = false

  view {
    query = <<-EOT
      SELECT
        e.execution_id,
        e.execution_ts,
        e.triggered_by,
        e.status,
        e.duration_seconds,
        COUNT(DISTINCT k.repo)                                                                     AS repos_processed,
        COUNT(DISTINCT k.repo) - COUNT(DISTINCT IF(k.status != 'ok', k.repo, NULL))               AS repos_ok,
        COUNT(DISTINCT IF(k.status = 'missing_branch', k.repo, NULL))                             AS repos_missing_branch,
        COUNT(DISTINCT IF(k.status = 'error',          k.repo, NULL))                             AS repos_with_error,
        COUNT(DISTINCT IF(k.severity != 'none',        k.repo, NULL))                             AS repos_with_drift,
        -- repos with file changes in a critical direction (same convention as commit_drift):
        --   production not in master  (left=master,  right=production)
        --   test not in master        (left=master,  right=test)
        --   production not in test    (left=test,    right=production)
        COUNT(DISTINCT IF(
          k.unique_files > 0 AND (
            (k.left_branch LIKE '%master%' AND k.right_branch LIKE '%production%') OR
            (k.left_branch LIKE '%master%' AND k.right_branch LIKE '%test%')       OR
            (k.left_branch LIKE '%test%'   AND k.right_branch LIKE '%production%')
          ), k.repo, NULL
        ))                                                                                          AS repos_critical_drift,
        COALESCE(SUM(k.unique_files), 0)                                                           AS total_files_in_drift
      FROM `${var.reporting_project_id}.devops_reports.executions` e
      LEFT JOIN `${var.reporting_project_id}.devops_reports.branch_drift_kpis` k
        USING (execution_id)
      WHERE e.report_type = 'file_drift'
        AND (k.drift_type = 'content' OR k.drift_type IS NULL)
        AND (k.repo IS NULL OR k.repo NOT IN (
          'central_cicd_templates', 'cloud_run_source', 'dataflow', 'dataquality_framework'
        ))
      GROUP BY 1, 2, 3, 4, 5
    EOT
    use_legacy_sql = false
  }
}

# ---------------------------------------------------------------------------
# Looker Studio view — orphan_datasets job-level run summary
# ---------------------------------------------------------------------------
# One row per Cloud Run job execution of orphan_datasets.
# Derives counts from the orphan_datasets table (only orphan rows are stored;
# datasets_scanned is not yet persisted — add it to repos_total in the script
# as a follow-up to surface the "did it scan anything" signal).
resource "google_bigquery_table" "orphan_datasets_job_summary" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "orphan_datasets_job_summary"
  deletion_protection = false

  view {
    query = <<-EOT
      SELECT
        e.execution_id,
        e.execution_ts,
        e.triggered_by,
        e.status,
        e.duration_seconds,
        COALESCE(e.repos_total, 0)           AS datasets_scanned,
        COUNT(DISTINCT o.dataset_name)       AS orphan_datasets_found,
        COALESCE(SUM(o.table_count), 0)      AS total_objects_in_orphans,
        COUNT(DISTINCT IF(o.risk_score >= 2, o.dataset_name, NULL)) AS high_risk_datasets
      FROM `${var.reporting_project_id}.devops_reports.executions` e
      LEFT JOIN `${var.reporting_project_id}.devops_reports.orphan_datasets` o
        USING (execution_id)
      WHERE e.report_type = 'orphan_datasets'
      GROUP BY 1, 2, 3, 4, 5, 6
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
          AND e.project_name != '_job_summary'
        GROUP BY e.execution_id, COALESCE(e.project_name, f.product), DATE(e.execution_ts), e.execution_ts
      ),

      env_latest AS (
        SELECT *
        FROM env_per_exec
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY repo, run_date ORDER BY execution_ts DESC
        ) = 1
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
          SUM(CASE
            WHEN k.status = 'ok'
              AND (
                (REGEXP_EXTRACT(k.right_branch, r'origin/(.+)') = 'production'
                 AND REGEXP_EXTRACT(k.left_branch,  r'origin/(.+)') IN ('master','test'))
                OR
                (REGEXP_EXTRACT(k.right_branch, r'origin/(.+)') = 'test'
                 AND REGEXP_EXTRACT(k.left_branch,  r'origin/(.+)') = 'master')
              )
            THEN COALESCE(k.unique_files, 0)
            ELSE 0
          END) AS file_drift
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
      FROM env_latest env
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

# ---------------------------------------------------------------------------
# Looker Studio view — commit drift detail report
# ---------------------------------------------------------------------------
# One row per repo × drift direction × run (last 90 days).
# run_number: 1 = latest run for run_date, 2 = previous, etc.
# In Looker Studio connect to this view directly; add Filter Controls on
# run_date (date picker) and run_number (dropdown) to select a specific run.
resource "google_bigquery_table" "commit_drift_report" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "commit_drift_report"
  deletion_protection = false

  view {
    query = <<-EOT
      WITH latest_exec AS (
        SELECT
          execution_id,
          execution_ts,
          DATE(execution_ts, 'Europe/Berlin')             AS run_date,
          ROW_NUMBER() OVER (
            PARTITION BY DATE(execution_ts, 'Europe/Berlin')
            ORDER BY execution_ts DESC
          )                                               AS run_number,
          environment,
          status,
          triggered_by
        FROM `${var.reporting_project_id}.devops_reports.executions`
        WHERE report_type = 'commit_drift'
          AND status      = 'success'
      ),

      kpi_summary AS (
        SELECT
          e.execution_id,
          e.run_date,
          e.run_number,
          e.execution_ts,
          e.environment,
          e.triggered_by,
          k.repo,
          k.left_branch,
          k.right_branch,
          CASE CONCAT(REGEXP_EXTRACT(k.right_branch, r'origin/(.+)'),
                      ' not in ',
                      REGEXP_EXTRACT(k.left_branch,  r'origin/(.+)'))
            WHEN 'test not in master'       THEN '⚠ test not in master'
            WHEN 'production not in test'   THEN '⚠ production not in test'
            WHEN 'production not in master' THEN '⚠ production not in master'
            ELSE CONCAT(REGEXP_EXTRACT(k.right_branch, r'origin/(.+)'),
                        ' not in ',
                        REGEXP_EXTRACT(k.left_branch,  r'origin/(.+)'))
          END                          AS drift_direction,
          k.unique_commits,
          k.unique_files,
          k.severity,
          k.status                     AS branch_status,
          k.comparison_mode,
          CASE k.severity
            WHEN 'high'   THEN 1
            WHEN 'medium' THEN 2
            WHEN 'low'    THEN 3
            WHEN 'none'   THEN 4
            ELSE               5
          END                          AS severity_sort
        FROM `${var.reporting_project_id}.devops_reports.branch_drift_kpis` k
        JOIN latest_exec e USING (execution_id)
        WHERE k.drift_type = 'commit'
          AND k.status     = 'ok'
      ),

      evidence_agg AS (
        SELECT
          ev.execution_id,
          ev.repo,
          ev.discrepancy,
          COUNT(DISTINCT ev.commit_sha) AS distinct_commits,
          COUNT(DISTINCT ev.author)     AS distinct_authors,
          COUNT(DISTINCT ev.file_path)  AS distinct_files,
          MIN(ev.commit_date)           AS earliest_commit_date,
          MAX(ev.commit_date)           AS latest_commit_date
        FROM `${var.reporting_project_id}.devops_reports.branch_drift_evidence` ev
        JOIN latest_exec USING (execution_id)
        WHERE ev.drift_type = 'commit'
        GROUP BY ev.execution_id, ev.repo, ev.discrepancy
      )

      SELECT
        ks.run_date,
        ks.run_number,
        ks.execution_ts,
        ks.environment,
        ks.triggered_by,
        ks.repo,
        ks.drift_direction,
        ks.left_branch,
        ks.right_branch,
        ks.unique_commits,
        ks.unique_files,
        ks.severity,
        ks.branch_status,
        ks.comparison_mode,
        ea.distinct_authors,
        ea.earliest_commit_date,
        ea.latest_commit_date
      FROM kpi_summary ks
      LEFT JOIN evidence_agg ea
        ON  ea.execution_id  = ks.execution_id
        AND ea.repo          = ks.repo
        AND ea.discrepancy   = CONCAT(
              REGEXP_EXTRACT(ks.right_branch, r'origin/(.+)'), '_not_in_',
              REGEXP_EXTRACT(ks.left_branch,  r'origin/(.+)')
            )
      ORDER BY ks.severity_sort, ks.unique_commits DESC, ks.repo, ks.left_branch
    EOT
    use_legacy_sql = false
  }
}

# ---------------------------------------------------------------------------
# Looker Studio view — commit drift evidence (drill-through)
# ---------------------------------------------------------------------------
# One row per file per commit (evidence level). Joins branch_drift_evidence to
# branch_drift_kpis to recover human-readable drift_direction (including ⚠ prefix
# for the 3 critical directions). Use as a second data source in the Commit Drift
# dashboard for the drill-through table showing repo, direction, SHA, author, date, file.
resource "google_bigquery_table" "commit_drift_evidence_report" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "commit_drift_evidence_report"
  deletion_protection = false

  view {
    query = <<-EOT
      WITH exec AS (
        SELECT
          execution_id,
          execution_ts,
          DATE(execution_ts, 'Europe/Berlin')             AS run_date,
          ROW_NUMBER() OVER (
            PARTITION BY DATE(execution_ts, 'Europe/Berlin')
            ORDER BY execution_ts DESC
          )                                               AS run_number
        FROM `${var.reporting_project_id}.devops_reports.executions`
        WHERE report_type = 'commit_drift'
          AND status      = 'success'
      ),
      kpi AS (
        SELECT
          execution_id,
          repo,
          CONCAT(
            CASE REGEXP_EXTRACT(right_branch, r'origin/(.+)')
              WHEN 'production' THEN 'prod'
              ELSE REGEXP_EXTRACT(right_branch, r'origin/(.+)')
            END,
            '_not_in_',
            CASE REGEXP_EXTRACT(left_branch, r'origin/(.+)')
              WHEN 'production' THEN 'prod'
              ELSE REGEXP_EXTRACT(left_branch, r'origin/(.+)')
            END
          )                                 AS discrepancy,
          CASE CONCAT(REGEXP_EXTRACT(right_branch, r'origin/(.+)'),
                      ' not in ',
                      REGEXP_EXTRACT(left_branch,  r'origin/(.+)'))
            WHEN 'test not in master'       THEN '⚠ test not in master'
            WHEN 'production not in test'   THEN '⚠ production not in test'
            WHEN 'production not in master' THEN '⚠ production not in master'
            ELSE CONCAT(REGEXP_EXTRACT(right_branch, r'origin/(.+)'),
                        ' not in ',
                        REGEXP_EXTRACT(left_branch,  r'origin/(.+)'))
          END                               AS drift_direction
        FROM `${var.reporting_project_id}.devops_reports.branch_drift_kpis`
        WHERE drift_type = 'commit'
          AND status     = 'ok'
      )
      SELECT
        ex.run_date,
        ex.run_number,
        ex.execution_ts,
        ev.repo,
        k.drift_direction,
        ev.commit_sha,
        ev.author,
        ev.commit_date,
        ev.file_path,
        ev.problem_statement
      FROM `${var.reporting_project_id}.devops_reports.branch_drift_evidence` ev
      JOIN exec ex USING (execution_id)
      JOIN kpi  k  ON  k.execution_id = ev.execution_id
                   AND k.repo         = ev.repo
                   AND k.discrepancy  = ev.discrepancy
      WHERE ev.drift_type = 'commit'
      ORDER BY ex.run_date DESC, ex.run_number, ev.repo, k.drift_direction, ev.commit_date
    EOT
    use_legacy_sql = false
  }
}

# ---------------------------------------------------------------------------
# Looker Studio view — file drift detail report
# ---------------------------------------------------------------------------
# One row per repo × drift direction × run (last 90 days).
# run_number: 1 = latest run for run_date, 2 = previous, etc.
# In Looker Studio connect to this view directly; add Filter Controls on
# run_date (date picker) and run_number (dropdown) to select a specific run.
resource "google_bigquery_table" "file_drift_report" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "file_drift_report"
  deletion_protection = false

  view {
    query = <<-EOT
      WITH latest_exec AS (
        SELECT
          execution_id,
          execution_ts,
          DATE(execution_ts, 'Europe/Berlin')             AS run_date,
          ROW_NUMBER() OVER (
            PARTITION BY DATE(execution_ts, 'Europe/Berlin')
            ORDER BY execution_ts DESC
          )                                               AS run_number,
          environment,
          status,
          triggered_by
        FROM `${var.reporting_project_id}.devops_reports.executions`
        WHERE report_type = 'file_drift'
          AND status      = 'success'
      ),

      kpi_summary AS (
        SELECT
          e.execution_id,
          e.run_date,
          e.run_number,
          e.execution_ts,
          e.environment,
          e.triggered_by,
          k.repo,
          k.left_branch,
          k.right_branch,
          CONCAT(
            REGEXP_EXTRACT(k.right_branch, r'origin/(.+)'),
            ' differs from ',
            REGEXP_EXTRACT(k.left_branch,  r'origin/(.+)')
          )                            AS drift_direction,
          k.unique_commits,
          k.unique_files,
          k.severity,
          k.status                     AS branch_status,
          k.comparison_mode,
          CASE k.severity
            WHEN 'high'   THEN 1
            WHEN 'medium' THEN 2
            WHEN 'low'    THEN 3
            WHEN 'none'   THEN 4
            ELSE               5
          END                          AS severity_sort
        FROM `${var.reporting_project_id}.devops_reports.branch_drift_kpis` k
        JOIN latest_exec e USING (execution_id)
        WHERE k.drift_type = 'content'
          AND k.status     = 'ok'
      ),

      evidence_agg AS (
        SELECT
          ev.execution_id,
          ev.repo,
          ev.discrepancy,
          COUNT(DISTINCT ev.file_path)                                         AS distinct_files,
          COUNTIF(UPPER(ev.change_type) = 'A')                                AS files_added,
          COUNTIF(UPPER(ev.change_type) = 'M')                                AS files_modified,
          COUNTIF(UPPER(ev.change_type) = 'D')                                AS files_deleted,
          COUNTIF(ev.change_type NOT IN ('A','M','D') OR ev.change_type IS NULL) AS files_other,
          COUNT(DISTINCT ev.author)                                            AS distinct_authors,
          MIN(ev.commit_date)                                                  AS earliest_change_date,
          MAX(ev.commit_date)                                                  AS latest_change_date
        FROM `${var.reporting_project_id}.devops_reports.branch_drift_evidence` ev
        JOIN latest_exec USING (execution_id)
        WHERE ev.drift_type = 'content'
        GROUP BY ev.execution_id, ev.repo, ev.discrepancy
      )

      SELECT
        ks.run_date,
        ks.run_number,
        ks.execution_ts,
        ks.environment,
        ks.triggered_by,
        ks.repo,
        ks.drift_direction,
        ks.left_branch,
        ks.right_branch,
        ks.comparison_mode,
        ks.unique_commits,
        ks.unique_files,
        ks.severity,
        ks.branch_status,
        ea.distinct_authors,
        ea.files_added,
        ea.files_modified,
        ea.files_deleted,
        ea.files_other,
        ea.earliest_change_date,
        ea.latest_change_date
      FROM kpi_summary ks
      LEFT JOIN evidence_agg ea
        ON  ea.execution_id = ks.execution_id
        AND ea.repo         = ks.repo
        AND ea.discrepancy  = CONCAT(
              REGEXP_EXTRACT(ks.right_branch, r'origin/(.+)'), '_not_in_',
              REGEXP_EXTRACT(ks.left_branch,  r'origin/(.+)')
            )
      ORDER BY ks.severity_sort, ks.unique_files DESC, ks.repo, ks.left_branch
    EOT
    use_legacy_sql = false
  }
}

# ---------------------------------------------------------------------------
# File-content branch drift — file-level evidence (drill-through for Looker)
# ---------------------------------------------------------------------------

resource "google_bigquery_table" "file_drift_evidence_report" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "file_drift_evidence_report"
  deletion_protection = false

  view {
    query = <<-EOT
      WITH latest_exec AS (
        SELECT
          execution_id,
          execution_ts,
          DATE(execution_ts, 'Europe/Berlin') AS run_date,
          ROW_NUMBER() OVER (
            PARTITION BY DATE(execution_ts, 'Europe/Berlin')
            ORDER BY execution_ts DESC
          )                                   AS run_number,
          environment,
          triggered_by
        FROM `${var.reporting_project_id}.devops_reports.executions`
        WHERE report_type = 'file_drift'
          AND status      = 'success'
      )

      SELECT
        e.run_date,
        e.run_number,
        e.execution_ts,
        e.environment,
        e.triggered_by,
        ev.repo,
        ev.discrepancy,
        CONCAT(
          SPLIT(ev.discrepancy, '_not_in_')[OFFSET(0)],
          ' differs from ',
          SPLIT(ev.discrepancy, '_not_in_')[OFFSET(1)]
        )                                     AS drift_direction,
        ev.file_path,
        CASE UPPER(ev.change_type)
          WHEN 'A' THEN 'added'
          WHEN 'M' THEN 'modified'
          WHEN 'D' THEN 'deleted'
          ELSE          'other'
        END                                   AS change_label,
        ev.change_type                        AS raw_change_type,
        ev.author                             AS last_author,
        ev.commit_date                        AS last_changed_at,
        ev.commit_sha                         AS last_commit_sha,
        ev.problem_statement
      FROM `${var.reporting_project_id}.devops_reports.branch_drift_evidence` ev
      JOIN latest_exec e USING (execution_id)
      WHERE ev.drift_type = 'content'
        AND ev.file_path  IS NOT NULL
      ORDER BY
        e.run_date        DESC,
        e.run_number,
        ev.repo,
        ev.discrepancy,
        ev.file_path
    EOT
    use_legacy_sql = false
  }
}

# ---------------------------------------------------------------------------
# BQ structure drift — partitioning / clustering comparison across envs
# ---------------------------------------------------------------------------

resource "google_bigquery_table" "bq_structure_drift" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "bq_structure_drift"
  deletion_protection = true

  schema = jsonencode([
    { name = "run_id",        type = "STRING",    mode = "REQUIRED" },
    { name = "checked_at",    type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "dataset_id",    type = "STRING",    mode = "REQUIRED" },
    { name = "table_id",      type = "STRING",    mode = "REQUIRED" },
    { name = "table_type",    type = "STRING" },
    { name = "discrepancy",   type = "STRING",    mode = "REQUIRED" },
    { name = "attribute",     type = "STRING",    mode = "REQUIRED" },
    { name = "prod_value",    type = "STRING" },
    { name = "test_value",    type = "STRING" },
    { name = "dev_gke_value", type = "STRING" },
  ])

  time_partitioning {
    type  = "DAY"
    field = "checked_at"
  }

  clustering = ["dataset_id"]
}

resource "google_bigquery_table" "bq_structure_drift_report" {
  project             = var.reporting_project_id
  dataset_id          = google_bigquery_dataset.devops_reports.dataset_id
  table_id            = "bq_structure_drift_report"
  deletion_protection = false

  view {
    use_legacy_sql = false
    query          = <<-EOT
      SELECT
        run_id,
        checked_at,
        DATE(checked_at)  AS run_date,
        dataset_id,
        table_id,
        table_type,
        discrepancy,
        attribute,
        prod_value,
        test_value,
        dev_gke_value,
        ROW_NUMBER() OVER (
          PARTITION BY dataset_id, table_id, attribute
          ORDER BY checked_at DESC
        ) AS run_number
      FROM `${var.reporting_project_id}.devops_reports.bq_structure_drift`
    EOT
  }
}

