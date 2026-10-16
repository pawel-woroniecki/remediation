# Developer Onboarding & Contributing Guide

This guide is for developers taking over or extending this codebase. It covers local
development setup, how `entrypoint.sh` works, how to add a new report type end-to-end,
the CI/CD workflow, known tech debt, and team contacts.

---

## 1. Local development setup

### Prerequisites

- Python 3.11 (matches the `python:3.11-slim` Docker base image)
- Google Cloud SDK (`gcloud`) installed and authenticated
- Access to the GCP projects listed in `Readme.md`

### Environment setup

```bash
# Create and activate a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r "TEF remediation/requirements.txt"

# Authenticate to GCP (required for BigQuery + Secret Manager access)
gcloud auth application-default login
```

The six Python packages in `requirements.txt` are the same ones installed in the Docker
image: `google-cloud-bigquery`, `google-cloud-storage`, `google-cloud-secret-manager`,
`google-auth`, `requests`, and `pyyaml`.

### Running a report script locally

Each report script can be run directly without Cloud Run or Docker. Set a minimum of
two env vars so BigQuery audit rows are identifiable as local runs:

```bash
export EXECUTION_ID=local-test-001
export TRIGGERED_BY=developer
```

Then run the script with the flags it needs. Example for `env_drift` against one repo:

```bash
cd "TEF remediation"
python git_gcp_code_vs_environment_drift/generate_code_environment_drift_report.py \
  --gcp-project         tefde-gcp-fastoss-prod \
  --reporting-project   tefde-gcp-fastoss-dev \
  --reports-gcs-bucket  tefde-gcp-fastoss-dev-gcs-devops-reports \
  --target-env          prod \
  --git-ref             production \
  --project-name        <one-repo-name> \
  --repo-path           /path/to/cloned/repo
```

See each folder's `README-developer.md` for the exact local command and flags per script.
Pass `--no-bq` where supported to skip BigQuery writes during testing.

---

## 2. `entrypoint.sh` — how it works

`entrypoint.sh` is the Docker `ENTRYPOINT` used by every Cloud Run Job. It:

1. Auto-generates `EXECUTION_ID` (UUID4) if the caller did not supply one
2. Reads the **report type** from its first argument and validates it
3. Calls `clone_fastoss_b.py` to clone all repos in the GitLab subgroup
4. Routes to the appropriate Python script, forwarding any remaining CLI arguments

For `env_drift` specifically, repos are processed **in parallel** (capped at
`ENV_DRIFT_MAX_PARALLEL`). After all workers finish, a single job-level summary row is
written to `devops_reports.executions` with `project_name = '_job_summary'` — this is
what the Job Run Status dashboard reads.

### Environment variable reference

All variables are optional except `GCP_PROJECT`. Defaults match the values set in
`Terraform/Cloud Run Jobs.tf`.

| Variable | Default | Used by | Description |
|---|---|---|---|
| `GCP_PROJECT` | *(required)* | all | Project for Secret Manager (GitLab PAT fetch) |
| `GITLAB_BASE_URL` | `https://dot-portal.de.pri.o2.com/gitlab` | all | GitLab API base URL |
| `GITLAB_TOKEN_SECRET_ID` | `gitlab-token` | all | Secret Manager secret name holding the GitLab PAT |
| `SUBGROUP` | `ndl_core` | all | GitLab subgroup whose repos are cloned |
| `REPO_ROOT` | `/workspace/repos/fastossb` | all | Directory where repos are cloned |
| `CLONE_BRANCH` | *(not set)* | all | If set, clones this specific branch instead of the default |
| `EXCLUDE_REPOS` | *(not set)* | `env_drift`, `commit_drift`, `file_drift` | Space-separated repo names to skip; glob patterns supported (e.g. `demo_* staging_*`) |
| `ENV_DRIFT_MAX_PARALLEL` | `5` | `env_drift` | Max concurrent repo workers |
| `REPORTS_GCS_BUCKET` | *(not set)* | `bq_structure` | GCS bucket for uploading the dataset-mapping file |
| `EXECUTION_ID` | *(auto UUID4)* | all | Written to `executions`; set manually for local testing |
| `TRIGGERED_BY` | `manual` | all | Written to `executions` (`manual`, scheduler name, etc.) |
| `CLOUD_RUN_EXECUTION` | *(set by Cloud Run)* | `env_drift` | Cloud Run execution name; used as ID for the job-level summary row |

---

## 3. Adding a new report type — end-to-end

Use an existing report (e.g. `commit_drift`) as a reference throughout.

### Step 1 — Write the Python script

Place the script in the appropriate folder:

| Script type | Folder |
|---|---|
| Git vs GCP environment comparison | `git_gcp_code_vs_environment_drift/` |
| Git branch analysis | `git_branches_gap/` |
| BigQuery analysis | `bigquery_orphan_datasets/` |
| General / multi-purpose | `scripts/` |

The script must:
- Accept `--reporting-project`, `--reports-gcs-bucket`, and `--execution-id` as CLI flags
- Write **one row** to `devops_reports.executions` on completion (success or failure)
- Write findings to a dedicated BigQuery table (created in Step 2)
- Write a CSV summary to GCS under a subfolder named after the report type

### Step 2 — Add BigQuery table and view in Terraform

In `Terraform/BQ DS + Tables.tf`:

1. Add a `google_bigquery_table` resource for the findings table with its schema,
   partitioning, and clustering
2. Add a `google_bigquery_table` resource for a Looker Studio view — include a
   `run_number` window function (`ROW_NUMBER() OVER (PARTITION BY ... ORDER BY
   execution_ts DESC)`) so viewers can filter by run within a day

Run `terraform plan` — only the new resources should appear.

### Step 3 — Add a case to `entrypoint.sh`

```bash
my_new_report)
    WORKSPACE_ROOT="${REPO_ROOT:-/workspace/repos/fastossb}"
    GITLAB_BASE_URL="${GITLAB_BASE_URL:-https://dot-portal.de.pri.o2.com/gitlab}"

    clone_repos "$WORKSPACE_ROOT" "$GITLAB_BASE_URL"

    exec python3 "$SCRIPTS_DIR/my_new_report.py" \
        --root "$WORKSPACE_ROOT/${SUBGROUP:-ndl_core}" \
        "$@"
    ;;
```

Also add `my_new_report` to the valid-types list in the usage error messages at lines 24
and 304 of the file.

### Step 4 — Add the Cloud Run Job in Terraform

In `Terraform/Cloud Run Jobs.tf`, copy an existing job resource and change:
- `name` → `"devops-reports-my-new-report"`
- `args` → `["my_new_report"]`
- `env` blocks for any new environment variables the script needs

### Step 5 — Add a Cloud Scheduler trigger in Terraform

In `Terraform/scheduler.tf`:

1. Add a `schedule_my_new_report` entry in the `locals {}` block with a cron expression
2. Add a `google_cloud_scheduler_job` resource (copy an existing one; change the name,
   description, `schedule`, and the job name in the `uri`)

Pick a schedule time at least 10 minutes after the previous job to avoid simultaneous
GitLab clone load.

### Step 6 — Copy the script into the Docker image

In `Dockerfile.python`, add a `COPY` line:

```dockerfile
COPY scripts/my_new_report.py scripts/
```

(adjust the source path to match where the script lives)

### Step 7 — Update the CI build trigger

In `.gitlab-ci.yml`, if the script is in a new folder not already listed under
`build-reports` → `changes`, add it:

```yaml
- my_new_folder/**/*
```

Scripts already watched: `Dockerfile.python`, `requirements.txt`, `entrypoint.sh`,
`scripts/**/*`, `git_branches_gap/**/*`, `git_gcp_code_vs_environment_drift/**/*`,
`bigquery_orphan_datasets/**/*`, `clone_all_groups_repo/**/*`.

### Step 8 — Update documentation

| File | What to add |
|---|---|
| `TEF remediation/Readme.md` | Row in the Reports table; row in the BigQuery Reporting Model table |
| `Instructions/Running the Reports.md` | Row in both the jobs table and the scheduler table |
| `Instructions/Building and Releasing a New Image Version.md` | Job name in the Method B job list |
| `scripts/README.md` or a new `README.md` | Usage docs for the new script |
| `CONTRIBUTING.md` (this file) | Any new env vars in Section 2 |
| New file: `Instructions/Building the <Name> Dashboard.md` | Step-by-step Looker Studio setup |

### Step 9 — Apply and verify

```bash
# Apply Terraform changes
cd "TEF remediation/Terraform"
terraform plan    # confirm only the new resources appear
terraform apply

# Push code — CI builds and pushes the new image automatically
git add <changed files>
git commit -m "feat: add my_new_report report type"
git push origin main

# Trigger a test run
gcloud run jobs execute devops-reports-my-new-report \
  --project=tefde-gcp-fastoss-dev-gke \
  --region=europe-west3

# Check the result
gcloud run jobs executions list \
  --job=devops-reports-my-new-report \
  --project=tefde-gcp-fastoss-dev-gke \
  --region=europe-west3
```

---

## 4. Git and CI workflow

- **Branch strategy:** work on feature branches; open a Merge Request into `main`
- **CI runs automatically on `main`:**
  - `build-reports` — triggers when any watched file changes; builds + Trivy scans + pushes the image
  - `terraform-plan` — triggers on `Terraform/**/*` changes; runs plan only (informational)
  - `create-release` — triggers on a `vX.Y.Z` annotated tag push
- **CI never runs `terraform apply`** — all infrastructure changes require a manual
  `terraform apply` from an authenticated terminal; see `Instructions/Building and
  Releasing a New Image Version.md` for the full release workflow
- **Releases:** `git tag -a v4.1.0 -m "Release v4.1.0: <summary>" && git push origin v4.1.0`

---

## 5. Known issues and tech debt

| Item | Status | Notes |
|---|---|---|
| Commit drift suppression | **On hold** — pending team discussion | A plan exists for suppressing known-good drift entries via a Google Form + Apps Script → BigQuery approach. No code changes yet. |
| CI uses a long-lived SA key (`GCP_SA_KEY`) | Tech debt | Upgrade path to keyless Workload Identity Federation is documented in the `.gitlab-ci.yml` comments. Eliminates the need for a JSON key in GitLab CI variables. |
| `backfill_discrepancy_names.sql` | Already applied (one-time fix) | Fixed abbreviated discrepancy names in `branch_drift_evidence` (commit `309493f`). Safe to re-run but not needed — kept for reference. |
| `terraform apply` is manual | By design | CI runs only `terraform plan`. Applying requires a human to review the plan and run `terraform apply` locally. |
| `organize_tf_export.py` has a hardcoded `--base-dir` default | Minor tech debt | The default points to `/home/nq10083194` (original author's Cloud Shell home). Always override with `--base-dir` when running in a new Cloud Shell session. |

---

## 6. Team contacts and escalation

| Team | Responsible for | Contact |
|---|---|---|
| **TEF IAM Team** | Service account `devops-reports-runner`, all IAM grants in `IAM_admin_instructions.md` | *[fill in: email / ticket queue]* |
| **TEF Networking Team** | VPC Access Connector `fastoss-dev-gke-connector`, Shared VPC, firewall/egress rules | *[fill in: email / ticket queue]* |
| **GitLab admin** | Group Access Token renewal for `gitlab-token` in Secret Manager | *[fill in: email / ticket queue]* |

### Most common failure: GitLab PAT expiry

If **all jobs fail simultaneously** with authentication / 401 errors, the GitLab PAT has
expired. Follow the full step-by-step rotation procedure in
[`Instructions/Rotating the GitLab PAT.md`](../Instructions/Rotating%20the%20GitLab%20PAT.md).

In brief: create a new Group Access Token in GitLab (`read_api` + `read_repository`
scopes), load it into Secret Manager, run a test job, then disable the old version:

```bash
gcloud secrets versions add gitlab-token \
  --project=tefde-gcp-fastoss-dev-gke \
  --data-file=- <<< "NEW_PAT_VALUE"
```

Prefer a **Group Access Token** over a Personal Access Token so it does not expire when
an individual leaves.
