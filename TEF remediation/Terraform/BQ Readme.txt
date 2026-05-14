Yes — below is **production‑ready Terraform** to create **all BigQuery resources** for the unified schema we defined.  
This is **copy‑pasteable**, modular, and works with **existing CSV ingestion**.

I’ll structure it as:

1.  **Provider & variables**
2.  **Dataset**
3.  **Tables (one per report type)**
4.  **Optional best‑practice settings**

***

# 1️⃣ Provider & Variables

```hcl
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
  description = "GCP project ID"
}

variable "region" {
  type        = string
  default     = "europe-west3"
}

variable "dataset_id" {
  type        = string
  default     = "devops_reports"
}
```

***

# 2️⃣ BigQuery Dataset

```hcl
resource "google_bigquery_dataset" "devops_reports" {
  dataset_id = var.dataset_id
  project    = var.project_id
  location   = "EU"

  description = "Unified DevOps governance and drift reporting"

  labels = {
    domain = "devops"
    owner  = "platform"
  }
}
```

***

# 3️⃣ Tables

## ✅ 3.1 `executions` (root table)

```hcl
resource "google_bigquery_table" "executions" {
  dataset_id = google_bigquery_dataset.devops_reports.dataset_id
  table_id   = "executions"

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED" },
    { name = "report_type", type = "STRING", mode = "REQUIRED" },
    { name = "execution_ts", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "environment", type = "STRING" },
    { name = "git_ref", type = "STRING" },
    { name = "source_mode", type = "STRING" },
    { name = "triggered_by", type = "STRING" },
    { name = "status", type = "STRING" },
    { name = "duration_seconds", type = "INT64" }
  ])

  time_partitioning {
    type  = "DAY"
    field = "execution_ts"
  }
}
```

***

## ✅ 3.2 `entities`

```hcl
resource "google_bigquery_table" "entities" {
  dataset_id = google_bigquery_dataset.devops_reports.dataset_id
  table_id   = "entities"

  schema = jsonencode([
    { name = "entity_id", type = "STRING", mode = "REQUIRED" },
    { name = "entity_type", type = "STRING", mode = "REQUIRED" },
    { name = "name", type = "STRING", mode = "REQUIRED" },
    { name = "domain", type = "STRING" },
    { name = "owner", type = "STRING" },
    { name = "lifecycle", type = "STRING" }
  ])
}
```

***

## ✅ 3.3 `branch_drift_kpis`

```hcl
resource "google_bigquery_table" "branch_drift_kpis" {
  dataset_id = google_bigquery_dataset.devops_reports.dataset_id
  table_id   = "branch_drift_kpis"

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED" },
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

  clustering = ["repo", "drift_type"]
}
```

***

## ✅ 3.4 `branch_drift_evidence`

```hcl
resource "google_bigquery_table" "branch_drift_evidence" {
  dataset_id = google_bigquery_dataset.devops_reports.dataset_id
  table_id   = "branch_drift_evidence"

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED" },
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

  clustering = ["repo", "discrepancy"]
}
```

***

## ✅ 3.5 `env_drift_findings`

```hcl
resource "google_bigquery_table" "env_drift_findings" {
  dataset_id = google_bigquery_dataset.devops_reports.dataset_id
  table_id   = "env_drift_findings"

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
```

***

## ✅ 3.6 `orphan_datasets`

```hcl
resource "google_bigquery_table" "orphan_datasets" {
  dataset_id = google_bigquery_dataset.devops_reports.dataset_id
  table_id   = "orphan_datasets"

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
```

***

## ✅ 3.7 `orphan_dataset_objects`

```hcl
resource "google_bigquery_table" "orphan_dataset_objects" {
  dataset_id = google_bigquery_dataset.devops_reports.dataset_id
  table_id   = "orphan_dataset_objects"

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
```

***

# 4️⃣ Recommended (Optional but Strongly Advised)

### ✅ Dataset‑wide retention

```hcl
default_table_expiration_ms = 31536000000 # 365 days
```

### ✅ Authorized views for Looker

*   Create a **BI service account**
*   Grant:

```text
roles/bigquery.dataViewer
roles/bigquery.jobUser
```

### ✅ Table naming stability

Never rename tables — version via:

*   `execution_id`
*   `report_type`

***

# ✅ What This Enables Immediately

*   ✅ Direct CSV → BigQuery loads
*   ✅ One unified Looker model
*   ✅ Trend analysis across *all* reports
*   ✅ Governance even if Git repos disappear

***

