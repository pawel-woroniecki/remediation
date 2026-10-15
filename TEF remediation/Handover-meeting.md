# Handover Meeting — Talking Points

## Point 2 — Architecture walkthrough (20 min)

**Start with the big picture — why Cloud Run Jobs, not a service or a script?**
- The reports only need to run once a day, take 5–10 minutes, and then stop. Cloud Run Jobs are billed only while running, scale to zero, and need no always-on server. The alternative (a VM or a Cloud Function) would either cost money 24/7 or hit timeout limits.

**The two-project split — and why it matters**
- `tefde-gcp-fastoss-dev-gke` hosts the compute: Cloud Run Jobs, Artifact Registry, Secret Manager, Cloud Scheduler, VPC connector. This is the "engine room."
- `tefde-gcp-fastoss-dev` hosts the data: BigQuery dataset, tables, views. This is the "reporting layer."
- The split exists because the org puts compute in `-gke` projects and data in `-dev` projects. The Terraform workspace manages both, but the Cloud Run service account is granted cross-project BigQuery write access.

**The data flow — walk through it step by step**
1. Cloud Scheduler fires once a day at the configured cron time, calling the Cloud Run Admin API
2. Cloud Run starts a container from the Docker image stored in Artifact Registry
3. `entrypoint.sh` runs — Phase 1 clones all GitLab repos, Phase 2 runs the report script
4. The script writes findings to BigQuery tables and a CSV to GCS
5. After the job finishes the container shuts down — nothing is running between executions
6. Looker Studio connects directly to BigQuery views — it reads on every dashboard load, so data is always fresh without any push from the jobs

**`entrypoint.sh` as the routing hub**
- Every Cloud Run Job runs the same Docker image — what makes each job different is the first argument passed to `entrypoint.sh` (e.g. `orphan_datasets`, `env_drift`, `bq_structure`)
- Phase 1 is always the same: clone all repos using the GitLab PAT fetched from Secret Manager
- Phase 2 dispatches to the right Python script via a `case` statement
- `env_drift` is the exception — it loops over every repo in parallel with a configurable concurrency cap (`ENV_DRIFT_MAX_PARALLEL=5`), then writes a single job-level summary row to BigQuery at the end

**The GitLab PAT — why Secret Manager, not a hardcoded token**
- Every report clones GitLab repos at runtime. The token gives read access to all repos in the `ndl_core` subgroup.
- Storing it in Secret Manager means: no token in code, no token in environment variable plain text in Terraform, and it can be rotated without redeploying the container.
- PAT expiry is the most common cause of all jobs failing at once — important to know who owns the renewal.

**What TEF IAM Team and Networking Team own — and why some Terraform resources are commented out**
- The service account `devops-reports-runner` is created by the TEF IAM Team, not by this workspace. All IAM bindings in the Terraform files are commented out — the team applies them manually to avoid conflicts with their own tooling.
- The VPC Access Connector is provisioned by the Networking Team. The Terraform workspace only reads it via a `data` source — it never creates it.
- Without the VPC connector, Cloud Run Jobs cannot reach the private GitLab instance (it's not publicly accessible).

**Security model**
- Cloud Run Jobs authenticate to GCP using Workload Identity — no JSON key file is ever downloaded or baked into the container
- The only long-lived credential is the GitLab PAT in Secret Manager, fetched at job start and never logged (the clone script redacts it from git subprocess error output before it can reach Cloud Logging)
- CI/CD still uses a JSON key (`GCP_SA_KEY`) to push images to Artifact Registry — the upgrade path to keyless CI is documented in `.gitlab-ci.yml` comments

---

## Point 3 — Code tour (20 min)

**Open the repo in the IDE and walk the folder structure top-down**

**`entrypoint.sh` — start here, not with the Python scripts**
- This is the most important file to understand first, because it's the glue that connects everything
- Show the `case` statement: each report type maps to exactly one Python script
- Show how `EXECUTION_ID` is auto-generated (UUID4 via Python) if not set — this ID links every BigQuery row from a single run together
- Show the `EXCLUDE_REPOS` glob matching — repos matching the pattern are silently skipped; this is how infra repos are excluded from commit/file drift checks

**`Dockerfile.python` — what's in the image**
- Base image is `python:3.11-slim`. The only additions are: `git` (for cloning), `google-cloud-cli` (for `gcloud storage cp` in env drift), and the six packages from `requirements.txt`
- Eight Python scripts are `COPY`'d in — show them by name and match each one to its report type. Point out that utility scripts (`backfill_*.py`, `organize_tf_export.py`, etc.) are NOT in the image — they run from Cloud Shell or a local terminal, not from Cloud Run
- The container runs as a non-root user (`appuser`) — defence in depth
- `HOME=/workspace` is set explicitly because `gcloud storage cp` tries to write config files to the home directory, and the non-root user has none

**`git_gcp_code_vs_environment_drift/` — the most complex report**
- `generate_code_environment_drift_report.py` compares what the Git source says should exist vs what's actually in GCP (BigQuery tables/views, GCS DAG files)
- Walk the high-level flow from `README-developer.md`: build source inventory from DDL files → stage GCS snapshot locally → compare → write findings
- Key nuance: schema comparison uses `canonical_bq_data_type()` to normalise type aliases (`INTEGER` → `INT64`) so the same type doesn't falsely appear as a mismatch
- This script runs once per repo — `entrypoint.sh` handles the parallelism, not the script itself

**`git_branches_gap/` — two scripts, one purpose**
- `report_branch_discrepancies_by_commit.py` — checks which commits exist in one branch but not another (six direction pairs: prod/test/master in all combinations)
- `report_branch_discrepancies_by_content.py` — checks which files differ between branches (same six directions)
- Both write to the same two BigQuery tables: `branch_drift_kpis` (one row per repo × direction) and `branch_drift_evidence` (one row per commit or file)
- The "critical" drift directions are: production not in master/test, test not in master — these get a `⚠` prefix in the views

**`bigquery_orphan_datasets/` and `scripts/compare_bq_structure.py`**
- `unmatched_bq_datasets_report.py`: scans all BigQuery datasets in the prod project, cross-references against the repos' declared `BQ_DATASET_NAMES` (from `.gitlab-ci.yml`), reports any dataset with no code owner
- `compare_bq_structure.py`: compares partitioning and clustering settings across prod/test/dev-gke — catches drift after Terraform exports are propagated between environments
- `bq_structure` is the only report type that first runs `generate_dataset_mapping.py` inside `entrypoint.sh` (to get the dataset→repo mapping) before calling the comparison script

**`Terraform/` — infrastructure as code**
- `BQ DS + Tables.tf` is the largest file — every BigQuery table schema and every Looker Studio view is defined here as HCL. When updating a view's SQL, edit the `query` heredoc and run `terraform apply` — the view updates in place with no data loss
- `Cloud Run Jobs.tf` defines all eight jobs (seven scheduled + one on-demand). Each job passes its report type as the first container argument and sets environment variables
- `scheduler.tf` creates seven Cloud Scheduler triggers, one per job. All are staggered 10 minutes apart starting at 05:00 to avoid hammering the GitLab clone endpoint simultaneously
- `backend.tf` — state is in GCS, not local. Always run `terraform init` after cloning the repo before any `plan` or `apply`

**`scripts/` — developer utilities, NOT deployed to Cloud Run**
- These run from Cloud Shell or a local terminal. The most important ones for a dev team: `generate_dataset_mapping.py` (on-demand Cloud Run job — run it when a new repo is added), `organize_tf_export_flat.py` + `propagate_tf_env.py` (BigQuery → Terraform export workflow, documented in `scripts/README-export-folders.md`)
- `backfill_discrepancy_names.sql` — a one-time fix already applied; kept for reference only

**`looker_sql/` — SQL reference files**
- These are no longer the primary data source for dashboards (the BQ views are), but they're useful for understanding the query logic and for running ad-hoc analysis in BigQuery Console
