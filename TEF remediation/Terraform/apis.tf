# ---------------------------------------------------------------------------
# GCP API Enablement
# ---------------------------------------------------------------------------
# APIs must be enabled before any other resources can be created.
# disable_on_destroy = false prevents accidental service disruption on destroy.

# --- Cloud Run / infrastructure project (tefde-gcp-fastoss-dev-gke) --------

resource "google_project_service" "run" {
  project            = var.project_id
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "secretmanager" {
  project            = var.project_id
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifactregistry" {
  project            = var.project_id
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "storage_gke" {
  project            = var.project_id
  service            = "storage.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iam_gke" {
  project            = var.project_id
  service            = "iam.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "cloudresourcemanager_gke" {
  project            = var.project_id
  service            = "cloudresourcemanager.googleapis.com"
  disable_on_destroy = false
}

# --- Reporting project (tefde-gcp-fastoss-dev) ------------------------------

resource "google_project_service" "bigquery" {
  project            = var.reporting_project_id
  service            = "bigquery.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iam_reporting" {
  project            = var.reporting_project_id
  service            = "iam.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "cloudresourcemanager_reporting" {
  project            = var.reporting_project_id
  service            = "cloudresourcemanager.googleapis.com"
  disable_on_destroy = false
}
