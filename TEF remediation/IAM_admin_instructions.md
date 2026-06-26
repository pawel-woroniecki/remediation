# GCP IAM Administrator Instructions — DevOps Reports Service Account

## Overview

This document lists every IAM binding that must be granted to the
`devops-reports-runner` service account for the TEF remediation DevOps
Reports solution to function correctly.

**Service account email:**
```
devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com
```

Permissions span three GCP projects:

| GCP Project | Role in the solution |
|---|---|
| `tefde-gcp-fastoss-dev-gke` | Compute project — Cloud Run Jobs, UI Service, GCS bucket, Secret Manager, Artifact Registry |
| `tefde-gcp-fastoss-dev` | Reporting project — BigQuery `devops_reports` dataset |
| `tefde-gcp-fastoss-prod` | Scan project — BigQuery datasets inspected by the orphan datasets report |

> **Note:** None of these bindings are applied by `terraform apply` — every
> corresponding `google_*_iam_member` resource in the Terraform files is
> commented out. The service account itself is also created and owned by
> the TEF IAM Team, not by this Terraform workspace. This document is the
> authoritative list the TEF IAM Team applies manually; use it to apply the
> grants or to audit that they're all in place.

---

## Prerequisites

Before granting any permissions:

1. The service account is created and owned by the TEF IAM Team — it must
   already exist before any of the grants below can be applied. Verify with:
   ```bash
   gcloud iam service-accounts describe \
     devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com \
     --project=tefde-gcp-fastoss-dev-gke
   ```
   If it does not exist yet, request it from the TEF IAM Team rather than
   creating it yourself — do not run `gcloud iam service-accounts create`
   for this SA.

2. You must hold one of the following roles on **each** project where you
   are granting permissions:
   - `roles/resourcemanager.projectIamAdmin`
   - `roles/owner`

---

## IAM Grants

### Project: `tefde-gcp-fastoss-dev-gke`

---

#### Grant 1 — Secret Manager: read the GitLab PAT

**Why:** The clone script reads the GitLab Personal Access Token from
Secret Manager at job runtime.

**Resource:** Secret `gitlab-token` in project `tefde-gcp-fastoss-dev-gke`
**Role:** `roles/secretmanager.secretAccessor`

**gcloud CLI:**
```bash
gcloud secrets add-iam-policy-binding gitlab-token \
  --project=tefde-gcp-fastoss-dev-gke \
  --role=roles/secretmanager.secretAccessor \
  --member="serviceAccount:devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com"
```

**GCP Console:**
1. Navigate to **Security → Secret Manager**
2. Click on the secret `gitlab-token`
3. Select the **Permissions** tab
4. Click **Grant Access**
5. New principals: `devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com`
6. Role: `Secret Manager Secret Accessor`
7. Click **Save**

---

#### Grant 2 — GCS bucket: write report CSV outputs

**Why:** All four report scripts upload CSV output files to this bucket
after each run.

**Resource:** Bucket `tefde-gcp-fastoss-dev-gcs-devops-reports`
**Role:** `roles/storage.objectCreator`

**gcloud CLI:**
```bash
gcloud storage buckets add-iam-policy-binding \
  gs://tefde-gcp-fastoss-dev-gcs-devops-reports \
  --role=roles/storage.objectCreator \
  --member="serviceAccount:devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com"
```

**GCP Console:**
1. Navigate to **Cloud Storage → Buckets**
2. Click on `tefde-gcp-fastoss-dev-gcs-devops-reports`
3. Select the **Permissions** tab
4. Click **Grant Access**
5. New principals: `devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com`
6. Role: `Storage Object Creator`
7. Click **Save**

---

#### Grant 3 — Artifact Registry: pull Docker image

**Why:** Cloud Run pulls the container image from Artifact Registry when
starting a job execution.

**Resource:** Repository `devops-reports` in region `europe-west3`, project `tefde-gcp-fastoss-dev-gke`
**Role:** `roles/artifactregistry.reader`

**gcloud CLI:**
```bash
gcloud artifacts repositories add-iam-policy-binding devops-reports \
  --project=tefde-gcp-fastoss-dev-gke \
  --location=europe-west3 \
  --role=roles/artifactregistry.reader \
  --member="serviceAccount:devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com"
```

**GCP Console:**
1. Navigate to **Artifact Registry → Repositories**
2. Click on `devops-reports`
3. Click **Show Info Panel** (top right) to open the permissions panel
4. Click **Add Principal**
5. New principals: `devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com`
6. Role: `Artifact Registry Reader`
7. Click **Save**

---

#### Grant 4 — Artifact Registry: push Docker images from CI/CD

**Why:** The GitLab CI pipeline authenticates as this service account to
push newly built Docker images to Artifact Registry.

**Resource:** Repository `devops-reports` in region `europe-west3`, project `tefde-gcp-fastoss-dev-gke`
**Role:** `roles/artifactregistry.writer`

**gcloud CLI:**
```bash
gcloud artifacts repositories add-iam-policy-binding devops-reports \
  --project=tefde-gcp-fastoss-dev-gke \
  --location=europe-west3 \
  --role=roles/artifactregistry.writer \
  --member="serviceAccount:devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com"
```

**GCP Console:**
1. Navigate to **Artifact Registry → Repositories**
2. Click on `devops-reports`
3. Click **Show Info Panel** → **Add Principal**
4. New principals: `devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com`
5. Role: `Artifact Registry Writer`
6. Click **Save**

---

#### Grant 5 — Project IAM: trigger Cloud Run Jobs

**Why:** The web UI backend calls the Cloud Run API to trigger report
jobs and read their execution status.

**Resource:** Project `tefde-gcp-fastoss-dev-gke`
**Role:** `roles/run.developer`

**gcloud CLI:**
```bash
gcloud projects add-iam-policy-binding tefde-gcp-fastoss-dev-gke \
  --role=roles/run.developer \
  --member="serviceAccount:devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com"
```

**GCP Console:**
1. Navigate to **IAM & Admin → IAM** (ensure project `tefde-gcp-fastoss-dev-gke` is selected)
2. Click **Grant Access**
3. New principals: `devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com`
4. Role: `Cloud Run Developer`
5. Click **Save`

---

#### Grant 10 — Service Account IAM: allow Terraform deployer to assign the SA to Cloud Run

**Why:** When `terraform apply` creates or updates a Cloud Run Service or Job that
uses `devops-reports-runner` as its runtime identity, GCP checks that the deploying
identity has `iam.serviceaccounts.actAs` on that SA. Without this, Cloud Run creation
fails with a 403. This grant goes on the SA itself, not on a project.

**Resource:** Service account `devops-reports-runner` in project `tefde-gcp-fastoss-dev-gke`
**Role:** `roles/iam.serviceAccountUser`
**Principal:** The identity that runs `terraform apply` — replace `DEPLOYER_IDENTITY`
below with the actual principal (e.g.
`serviceAccount:gitlab-runner@YOUR_PROJECT.iam.gserviceaccount.com` or
`user:you@example.com`).

**gcloud CLI:**
```bash
gcloud iam service-accounts add-iam-policy-binding \
  devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com \
  --project=tefde-gcp-fastoss-dev-gke \
  --role=roles/iam.serviceAccountUser \
  --member="DEPLOYER_IDENTITY"
```

**GCP Console:**
1. Navigate to **IAM & Admin → Service Accounts** (project `tefde-gcp-fastoss-dev-gke`)
2. Click on `devops-reports-runner`
3. Select the **Permissions** tab
4. Click **Grant Access**
5. New principals: the identity that runs `terraform apply`
6. Role: `Service Account User`
7. Click **Save**

---

#### Grant 11 — Service Account IAM: allow Cloud Scheduler to mint tokens as the SA

**Why:** The 4 report Cloud Run Jobs are triggered daily by Cloud Scheduler jobs
(`scheduler.tf`), which call the Cloud Run Admin API's `RunJob` method using an
OAuth token generated for `devops-reports-runner`. Cloud Scheduler doesn't use the
SA's own credentials directly — Google's per-project Cloud Scheduler service agent
must be granted permission to mint tokens on the SA's behalf. Without this grant,
every scheduled invocation fails with a 403 at firing time (not at `terraform apply`
time), so this is easy to miss until the first scheduled run.

**Resource:** Service account `devops-reports-runner` in project `tefde-gcp-fastoss-dev-gke`
**Role:** `roles/iam.serviceAccountTokenCreator`
**Principal:** The Cloud Scheduler service agent —
`serviceAccount:service-PROJECT_NUMBER@gcp-sa-cloudscheduler.iam.gserviceaccount.com`.
Replace `PROJECT_NUMBER` with the project number of `tefde-gcp-fastoss-dev-gke`
(find it with `gcloud projects describe tefde-gcp-fastoss-dev-gke --format="value(projectNumber)"`).
This service agent is auto-created the first time `cloudscheduler.googleapis.com`
is enabled on the project — confirm it exists before granting:
```bash
gcloud iam service-accounts describe \
  service-PROJECT_NUMBER@gcp-sa-cloudscheduler.iam.gserviceaccount.com
```

**gcloud CLI:**
```bash
gcloud iam service-accounts add-iam-policy-binding \
  devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com \
  --project=tefde-gcp-fastoss-dev-gke \
  --role=roles/iam.serviceAccountTokenCreator \
  --member="serviceAccount:service-PROJECT_NUMBER@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
```

**GCP Console:**
1. Navigate to **IAM & Admin → Service Accounts** (project `tefde-gcp-fastoss-dev-gke`)
2. Click on `devops-reports-runner`
3. Select the **Permissions** tab
4. Click **Grant Access**
5. New principals: `service-PROJECT_NUMBER@gcp-sa-cloudscheduler.iam.gserviceaccount.com`
6. Role: `Service Account Token Creator`
7. Click **Save**

---

### Project: `tefde-gcp-fastoss-dev`

---

#### Grant 6 — BigQuery dataset: write report data

**Why:** All four report scripts stream-insert rows into the tables in
the `devops_reports` dataset after each run.

**Resource:** Dataset `devops_reports` in project `tefde-gcp-fastoss-dev`
**Role:** `roles/bigquery.dataEditor`

**gcloud CLI:**
```bash
# Fetch the current policy, add the binding, and apply it
bq get-iam-policy --format=json \
  tefde-gcp-fastoss-dev:devops_reports > /tmp/bq_policy.json

# Edit /tmp/bq_policy.json to add the following entry inside "bindings":
# {
#   "role": "roles/bigquery.dataEditor",
#   "members": [
#     "serviceAccount:devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com"
#   ]
# }

bq set-iam-policy tefde-gcp-fastoss-dev:devops_reports /tmp/bq_policy.json
```

**GCP Console:**
1. Navigate to **BigQuery → Explorer**
2. Expand project `tefde-gcp-fastoss-dev`
3. Click the three-dot menu next to dataset `devops_reports` → **Share**
4. Click **Add Principal**
5. New principals: `devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com`
6. Role: `BigQuery Data Editor`
7. Click **Save**

---

#### Grant 7 — Project IAM: execute BigQuery jobs

**Why:** `bigquery.jobUser` is required at the project level to run any
BigQuery query or streaming insert (separate from the dataset-level role above).

**Resource:** Project `tefde-gcp-fastoss-dev`
**Role:** `roles/bigquery.jobUser`

**gcloud CLI:**
```bash
gcloud projects add-iam-policy-binding tefde-gcp-fastoss-dev \
  --role=roles/bigquery.jobUser \
  --member="serviceAccount:devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com"
```

**GCP Console:**
1. Navigate to **IAM & Admin → IAM** (ensure project `tefde-gcp-fastoss-dev` is selected)
2. Click **Grant Access**
3. New principals: `devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com`
4. Role: `BigQuery Job User`
5. Click **Save**

---

### Project: `tefde-gcp-fastoss-prod`

---

#### Grant 8 — Project IAM: read BigQuery metadata for orphan scan

**Why:** The orphan datasets report lists all datasets and queries
`INFORMATION_SCHEMA` for table and routine names. It reads only metadata
— never actual row data — so `metadataViewer` is sufficient and
`dataViewer` would be over-privileged.

**Resource:** Project `tefde-gcp-fastoss-prod`
**Role:** `roles/bigquery.metadataViewer`

**gcloud CLI:**
```bash
gcloud projects add-iam-policy-binding tefde-gcp-fastoss-prod \
  --role=roles/bigquery.metadataViewer \
  --member="serviceAccount:devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com"
```

**GCP Console:**
1. Navigate to **IAM & Admin → IAM** (ensure project `tefde-gcp-fastoss-prod` is selected)
2. Click **Grant Access**
3. New principals: `devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com`
4. Role: `BigQuery Metadata Viewer`
5. Click **Save**

---

#### Grant 9 — Project IAM: execute BigQuery jobs in prod

**Why:** `bigquery.jobUser` is required at the project level to run the
`INFORMATION_SCHEMA` queries that inspect dataset objects in prod.

**Resource:** Project `tefde-gcp-fastoss-prod`
**Role:** `roles/bigquery.jobUser`

**gcloud CLI:**
```bash
gcloud projects add-iam-policy-binding tefde-gcp-fastoss-prod \
  --role=roles/bigquery.jobUser \
  --member="serviceAccount:devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com"
```

**GCP Console:**
1. Navigate to **IAM & Admin → IAM** (ensure project `tefde-gcp-fastoss-prod` is selected)
2. Click **Grant Access**
3. New principals: `devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com`
4. Role: `BigQuery Job User`
5. Click **Save**

---

## Complete Grants Summary

| # | Project | Resource | Role | Principal |
|---|---|---|---|---|
| 1 | `tefde-gcp-fastoss-dev-gke` | Secret `gitlab-token` | `roles/secretmanager.secretAccessor` | `devops-reports-runner` SA |
| 2 | `tefde-gcp-fastoss-dev-gke` | Bucket `tefde-gcp-fastoss-dev-gcs-devops-reports` | `roles/storage.objectCreator` | `devops-reports-runner` SA |
| 3 | `tefde-gcp-fastoss-dev-gke` | AR repo `devops-reports` (europe-west3) | `roles/artifactregistry.reader` | `devops-reports-runner` SA |
| 4 | `tefde-gcp-fastoss-dev-gke` | AR repo `devops-reports` (europe-west3) | `roles/artifactregistry.writer` | `devops-reports-runner` SA |
| 5 | `tefde-gcp-fastoss-dev-gke` | Project | `roles/run.developer` | `devops-reports-runner` SA |
| 6 | `tefde-gcp-fastoss-dev` | BQ dataset `devops_reports` | `roles/bigquery.dataEditor` | `devops-reports-runner` SA |
| 7 | `tefde-gcp-fastoss-dev` | Project | `roles/bigquery.jobUser` | `devops-reports-runner` SA |
| 8 | `tefde-gcp-fastoss-prod` | Project | `roles/bigquery.metadataViewer` | `devops-reports-runner` SA |
| 9 | `tefde-gcp-fastoss-prod` | Project | `roles/bigquery.jobUser` | `devops-reports-runner` SA |
| 10 | `tefde-gcp-fastoss-dev-gke` | SA `devops-reports-runner` (resource) | `roles/iam.serviceAccountUser` | Terraform deployer identity |
| 11 | `tefde-gcp-fastoss-dev-gke` | SA `devops-reports-runner` (resource) | `roles/iam.serviceAccountTokenCreator` | Cloud Scheduler service agent |

---

## Verification

Run the following commands after granting all permissions to confirm
each binding is in place.

```bash
SA="serviceAccount:devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com"
DEPLOYER="DEPLOYER_IDENTITY"   # replace with the identity that runs terraform apply
SCHEDULER_AGENT="service-PROJECT_NUMBER@gcp-sa-cloudscheduler.iam.gserviceaccount.com"   # replace PROJECT_NUMBER

# Grant 1 — Secret Manager
gcloud secrets get-iam-policy gitlab-token \
  --project=tefde-gcp-fastoss-dev-gke \
  --format="table(bindings.role,bindings.members)" | grep "$SA"

# Grant 2 — GCS bucket
gcloud storage buckets get-iam-policy \
  gs://tefde-gcp-fastoss-dev-gcs-devops-reports \
  --format="table(bindings.role,bindings.members)" | grep "$SA"

# Grants 3 & 4 — Artifact Registry
gcloud artifacts repositories get-iam-policy devops-reports \
  --project=tefde-gcp-fastoss-dev-gke \
  --location=europe-west3 \
  --format="table(bindings.role,bindings.members)" | grep "$SA"

# Grant 5 — run.developer on compute project
gcloud projects get-iam-policy tefde-gcp-fastoss-dev-gke \
  --format="table(bindings.role,bindings.members)" | grep "$SA"

# Grant 6 — BigQuery dataset
bq get-iam-policy --format=prettyjson \
  tefde-gcp-fastoss-dev:devops_reports | grep -A2 "dataEditor"

# Grant 7 — bigquery.jobUser on reporting project
gcloud projects get-iam-policy tefde-gcp-fastoss-dev \
  --format="table(bindings.role,bindings.members)" | grep "$SA"

# Grants 8 & 9 — prod project
gcloud projects get-iam-policy tefde-gcp-fastoss-prod \
  --format="table(bindings.role,bindings.members)" | grep "$SA"
```

# Grant 10 — serviceAccountUser on the SA itself
gcloud iam service-accounts get-iam-policy \
  devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com \
  --project=tefde-gcp-fastoss-dev-gke \
  --format="table(bindings.role,bindings.members)" | grep "$DEPLOYER"

# Grant 11 — serviceAccountTokenCreator for the Cloud Scheduler service agent
gcloud iam service-accounts get-iam-policy \
  devops-reports-runner@tefde-gcp-fastoss-dev-gke.iam.gserviceaccount.com \
  --project=tefde-gcp-fastoss-dev-gke \
  --format="table(bindings.role,bindings.members)" | grep "$SCHEDULER_AGENT"
```

Each command should return at least one line containing the relevant
principal. If a command returns no output, that grant is missing.
