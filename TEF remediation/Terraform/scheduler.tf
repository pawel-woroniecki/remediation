# ---------------------------------------------------------------------------
# Cloud Scheduler — daily triggers for the 4 report Cloud Run Jobs
# ---------------------------------------------------------------------------
# Each scheduler job calls the Cloud Run Admin API's RunJob method directly
# (POST .../jobs/{job}:run), authenticating as the same devops-reports-runner
# SA already used to run these jobs from the UI. The target is run.googleapis.com
# itself (a *.googleapis.com Google API), so this uses oauth_token, not
# oidc_token — OIDC is for custom/non-Google endpoints.
# ---------------------------------------------------------------------------

locals {
  scheduler_time_zone = "Europe/Berlin" # Telefonica Germany (matches ui_invoker_member = "domain:telefonica.de")

  schedule_orphan_datasets = "0 5 * * *"  # 05:00
  schedule_env_drift       = "10 5 * * *" # 05:10
  schedule_commit_drift    = "20 5 * * *" # 05:20
  schedule_file_drift      = "30 5 * * *" # 05:30 — staggered 10 min apart to avoid simultaneous clone load
}

data "google_project" "this" {
  project_id = var.project_id
}

# ---------------------------------------------------------------------------
# Job 1: Orphan Datasets
# ---------------------------------------------------------------------------
resource "google_cloud_scheduler_job" "orphan_datasets" {
  name      = "devops-reports-orphan-datasets-trigger"
  project   = var.project_id
  region    = var.region
  schedule  = local.schedule_orphan_datasets
  time_zone = local.scheduler_time_zone

  depends_on = [google_project_service.cloudscheduler]

  http_target {
    uri         = "https://run.googleapis.com/v2/${google_cloud_run_v2_job.orphan_datasets.id}:run"
    http_method = "POST"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = var.cloud_run_sa_email
    }
  }

  retry_config {
    retry_count = 1
  }
}

# ---------------------------------------------------------------------------
# Job 2: Environment vs Code Drift
# ---------------------------------------------------------------------------
resource "google_cloud_scheduler_job" "env_drift" {
  name      = "devops-reports-env-drift-trigger"
  project   = var.project_id
  region    = var.region
  schedule  = local.schedule_env_drift
  time_zone = local.scheduler_time_zone

  depends_on = [google_project_service.cloudscheduler]

  http_target {
    uri         = "https://run.googleapis.com/v2/${google_cloud_run_v2_job.env_drift.id}:run"
    http_method = "POST"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = var.cloud_run_sa_email
    }
  }

  retry_config {
    retry_count = 1
  }
}

# ---------------------------------------------------------------------------
# Job 3: Commit-Based Branch Drift
# ---------------------------------------------------------------------------
resource "google_cloud_scheduler_job" "commit_drift" {
  name      = "devops-reports-commit-drift-trigger"
  project   = var.project_id
  region    = var.region
  schedule  = local.schedule_commit_drift
  time_zone = local.scheduler_time_zone

  depends_on = [google_project_service.cloudscheduler]

  http_target {
    uri         = "https://run.googleapis.com/v2/${google_cloud_run_v2_job.commit_drift.id}:run"
    http_method = "POST"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = var.cloud_run_sa_email
    }
  }

  retry_config {
    retry_count = 1
  }
}

# ---------------------------------------------------------------------------
# Job 4: File-Content Branch Drift
# ---------------------------------------------------------------------------
resource "google_cloud_scheduler_job" "file_drift" {
  name      = "devops-reports-file-drift-trigger"
  project   = var.project_id
  region    = var.region
  schedule  = local.schedule_file_drift
  time_zone = local.scheduler_time_zone

  depends_on = [google_project_service.cloudscheduler]

  http_target {
    uri         = "https://run.googleapis.com/v2/${google_cloud_run_v2_job.file_drift.id}:run"
    http_method = "POST"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = var.cloud_run_sa_email
    }
  }

  retry_config {
    retry_count = 1
  }
}

# ---------------------------------------------------------------------------
# IAM — allow the Cloud Scheduler service agent to mint OAuth tokens as the
# runner SA. Without this, every scheduled invocation fails with a 403 at
# firing time (not at terraform apply time).
#
# NOTE: IAM binding managed by the TEF IAM Team (see IAM_admin_instructions.md, Grant 11).
# The service account devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com
# is owned by that team. This resource is kept here for documentation purposes only.
# Do not apply if the TEF IAM Team manages permissions directly to avoid conflicts.
# resource "google_service_account_iam_member" "scheduler_can_impersonate_runner" {
#   service_account_id = "projects/${var.project_id}/serviceAccounts/${var.cloud_run_sa_email}"
#   role                = "roles/iam.serviceAccountTokenCreator"
#   member              = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
# }

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
output "scheduler_jobs" {
  value = {
    orphan_datasets = google_cloud_scheduler_job.orphan_datasets.name
    env_drift       = google_cloud_scheduler_job.env_drift.name
    commit_drift    = google_cloud_scheduler_job.commit_drift.name
    file_drift      = google_cloud_scheduler_job.file_drift.name
  }
  description = "Names of the Cloud Scheduler jobs that trigger each report daily."
}
