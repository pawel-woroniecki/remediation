# DevOps Reports UI

A lightweight web interface for triggering and monitoring the four DevOps governance reports.

The UI is a thin orchestration layer only — it has no business logic and does not touch scripts, BigQuery schemas, or GCS data directly.

---

## Architecture

```
Browser (HTTPS)
    │
    ▼
Cloud Run Service  (devops-reports-ui)
├── GET  /                            → serves index.html
├── GET  /api/reports                 → returns reports.yaml as JSON
├── POST /api/executions              → triggers a Cloud Run Job
├── GET  /api/executions/status?name= → polls Cloud Run execution status
└── GET  /api/executions              → lists 20 most recent rows from BigQuery
         │
         ├── Cloud Run Jobs API  (trigger + poll)
         └── BigQuery            (devops_reports.executions table)
```

The UI never reads from GCS directly. When a job completes, the `gcs_path` column written to BigQuery by the report script is returned and rendered as a clickable link. If `gcs_path` is absent (older rows), the link is reconstructed from `execution_id` as a fallback.

---

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI application — all API endpoints |
| `reports.yaml` | Declarative report metadata — drives form generation and parameter mapping |
| `static/index.html` | Single-page frontend — vanilla JS, no build step |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container definition (Python 3.11-slim, non-root user, port 8080, `PYTHONUNBUFFERED=1`) |

---

## Report Metadata (`reports.yaml`)

Each report entry controls how the form is rendered and how parameters are passed to the Cloud Run Job.

```yaml
commit_drift:
  label: "Commit-based branch drift"            # shown in the UI dropdown
  cloud_run_job: "devops-reports-commit-drift"  # Cloud Run Job name
  gcs_prefix: "branch-drift/commit"             # used to construct the GCS output link
  gcs_bucket_param: "gcs_bucket"                # which parameter holds the bucket name
  parameters:
    gcp_project:
      type: string
      required: true
      default: "tefde-gcp-fastoss-dev-gke"
      cli_flag: "--gcp-project"                 # passed as a CLI arg to the container
    subgroup:
      type: string
      required: false
      default: "ndl_core"
      env_var: "SUBGROUP"                       # passed as an env var override instead
```

**Parameter types:**

| `type` | Rendered as | Extra fields |
|---|---|---|
| `string` | Text input | `default`, `required`, `cli_flag` or `env_var` |
| `enum` | Dropdown | `options: [a, b]`, `default` |

A `default` of `<today>` is replaced at runtime with today's date (`YYYY-MM-DD`).

---

## API Reference

### `GET /api/reports`
Returns the full `reports.yaml` content as JSON. Used by the frontend to build forms.

### `POST /api/executions`
Triggers a Cloud Run Job execution.

**Request body:**
```json
{
  "report_type": "commit_drift",
  "parameters": {
    "gcp_project": "tefde-gcp-fastoss-dev-gke",
    "reporting_project": "tefde-gcp-fastoss-dev",
    "gcs_bucket": "tefde-gcp-fastoss-dev-gcs-devops-reports",
    "date_tag": "2026-05-14"
  }
}
```

**Response:**
```json
{
  "execution_name": "projects/tefde-gcp-fastoss-dev-gke/locations/europe-west3/executions/devops-reports-commit-drift-abc12",
  "status": "triggered"
}
```

Parameters with `cli_flag` are appended to the container `args`. Parameters with `env_var` are injected as environment variable overrides in the execution request.

`triggered_by` is read from the `X-Goog-Authenticated-User-Email` request header and stored in the `executions` BigQuery table. This header is only injected reliably when **Google Cloud IAP** is configured in front of the service; without IAP the value falls back to `"ui"` and can be spoofed by direct API callers.

### `GET /api/executions/status?name=<execution_name>`
Polls the Cloud Run execution status. When the execution succeeds, queries BigQuery for the `execution_id` and constructs the GCS Console link.

**Response (running):**
```json
{ "status": "running" }
```

**Response (succeeded):**
```json
{
  "status": "succeeded",
  "execution_id": "a3f1c842-...",
  "gcs_url": "https://console.cloud.google.com/storage/browser/tefde-gcp-fastoss-dev-gcs-devops-reports/branch-drift/commit/a3f1c842-..."
}
```

**Response (failed):**
```json
{ "status": "failed" }
```

### `GET /api/executions`
Returns the 20 most recent rows from `devops_reports.executions` in BigQuery.

**Response row:**
```json
{
  "execution_id": "a3f1c842-...",
  "report_type": "commit_drift",
  "execution_ts": "2026-05-15T10:00:00+00:00",
  "status": "success",
  "triggered_by": "user@telefonica.de",
  "duration_seconds": 142,
  "gcs_path": "gs://tefde-gcp-fastoss-dev-gcs-devops-reports/branch-drift/commit/a3f1c842-.../"
}
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GCP_PROJECT` | `tefde-gcp-fastoss-dev-gke` | Project where Cloud Run Jobs run |
| `REPORTING_PROJECT` | `tefde-gcp-fastoss-dev` | Project where BigQuery dataset lives |
| `REGION` | `europe-west3` | GCP region for Cloud Run |
| `GCS_BUCKET` | *(required)* | GCS bucket where report CSVs are uploaded; injected as the default value for `gcs_bucket` parameters |
| `BQ_SCAN_PROJECT` | *(required)* | BigQuery project scanned by the orphan-datasets report; injected as the default for `bq_scan_project` parameters |

These are set automatically by the Terraform Cloud Run Service definition in `ui_service.tf`.

---

## Deployment

### Step 1 — Build and push the UI image

The CI pipeline builds and pushes the image automatically on commits to the default branch. To build manually, run from the repo root:

```bash
SHA=$(git rev-parse --short HEAD)
IMAGE=europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports-ui

docker build -f ui/Dockerfile --build-arg BUILD_SHA=$SHA -t $IMAGE:$SHA -t $IMAGE:latest ui/
docker push $IMAGE:$SHA
docker push $IMAGE:latest
```

### Step 2 — Apply Terraform

```bash
cd Terraform
terraform init
terraform validate
terraform apply
```

This creates the `devops-reports-ui` Cloud Run Service. The service URL is printed as the `ui_url` output.

### Step 3 — Open the UI

```bash
gcloud run services describe devops-reports-ui \
  --project=tefde-gcp-fastoss-dev-gke \
  --region=europe-west3 \
  --format="value(status.url)"
```

Open the printed URL in a browser. Access is restricted to `domain:telefonica.de` accounts.

---

## IAM — Service Account

The UI runs as `devops-reports-runner@tefde-gcp-resvadm-prod-backend.iam.gserviceaccount.com` — the same service account used by the Cloud Run Jobs.

> **The service account is created and owned by the TEF IAM Team.** All IAM binding resources in Terraform are commented out for reference only. The TEF IAM Team applies the actual grants. See `IAM_admin_instructions.md` for the full list.

Relevant roles for the UI:

| Role | Project | Purpose |
|---|---|---|
| `roles/run.developer` | `tefde-gcp-fastoss-dev-gke` | Trigger Cloud Run Jobs and read execution status |
| `roles/bigquery.dataEditor` | `tefde-gcp-fastoss-dev` | Read/write `devops_reports` tables (shared with Cloud Run Jobs) |
| `roles/bigquery.jobUser` | `tefde-gcp-fastoss-dev` | Execute BigQuery queries |

The UI has no access to Secret Manager. The GitLab PAT is never visible to the UI.

> **Note:** The UI and Cloud Run Jobs share a single service account. This means job containers also hold `roles/run.developer` (the ability to trigger new jobs). This is a known trade-off accepted when service accounts were consolidated. See `Terraform/ui_service.tf` for details.

---

## Access Control

The Cloud Run Service is restricted to authenticated users in the `telefonica.de` Google Workspace domain, configured in `terraform.tfvars`:

```hcl
ui_invoker_member = "domain:telefonica.de"
```

To further restrict to a specific group:
```hcl
ui_invoker_member = "group:devops-team@telefonica.de"
```

For full browser-based SSO with a login page and reliable `triggered_by` audit logging, add Google Identity-Aware Proxy (IAP) via an HTTPS load balancer. Without IAP, the `triggered_by` field in BigQuery can be spoofed by direct API callers.

---

## Adding a New Report

1. Add an entry to `reports.yaml` following the existing structure.
2. Ensure the corresponding Cloud Run Job exists (add it to `Terraform/Cloud Run Jobs.tf` if not).
3. Rebuild and push the UI image — no backend code changes required.
