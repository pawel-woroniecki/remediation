# Running the DevOps Reports — End User Guide

This document explains how the 4 DevOps governance reports run across 6 Cloud Run Jobs,
how to trigger them manually, and how to change the automatic daily schedule.

| # | Report | Cloud Run Job name | Environment |
|---|---|---|---|
| 1 | Orphan BigQuery datasets | `devops-reports-orphan-datasets` | prod |
| 2 | Environment vs code drift | `devops-reports-env-drift` | prod |
| 3 | Commit-based branch drift | `devops-reports-commit-drift` | — (GitLab only) |
| 4 | File-content branch drift | `devops-reports-file-drift` | — (GitLab only) |
| 5 | Environment vs code drift | `devops-reports-env-drift-test` | test |
| 6 | Environment vs code drift | `devops-reports-env-drift-dev` | dev |

> Jobs 2, 5, and 6 run the same Environment Drift report against three separate GCP environments (prod, test, dev).

All reports write their results to BigQuery (`devops_reports` dataset in
`tefde-gcp-fastoss-dev`) and to CSV files in the GCS bucket
`tefde-gcp-fastoss-dev-gcs-devops-reports`. Dashboards are viewed in Looker Studio.

---

## 1. Automatic (scheduled) runs

All 6 Cloud Run Jobs run **automatically every day** — no action needed for routine reporting.

| Cloud Run Job | Scheduler trigger name | Time (Europe/Berlin) |
|---|---|---|
| `devops-reports-orphan-datasets` | `devops-reports-orphan-datasets-trigger` | 05:00 |
| `devops-reports-env-drift` | `devops-reports-env-drift-trigger` | 05:10 |
| `devops-reports-commit-drift` | `devops-reports-commit-drift-trigger` | 05:20 |
| `devops-reports-file-drift` | `devops-reports-file-drift-trigger` | 05:30 |
| `devops-reports-env-drift-test` | `devops-reports-env-drift-test-trigger` | 05:40 |
| `devops-reports-env-drift-dev` | `devops-reports-env-drift-dev-trigger` | 05:50 |

Times are staggered 10 minutes apart so the jobs don't all clone the same repos at once.

### How it works

A Cloud Scheduler job calls the Cloud Run Admin API directly once a day, asking it to start a
new execution of the corresponding Cloud Run Job — the same effect as triggering it manually,
just automated. No UI or person needs to be involved.

### Checking when a job last ran or will next run

```bash
gcloud scheduler jobs describe devops-reports-orphan-datasets-trigger \
  --project=tefde-gcp-fastoss-dev-gke \
  --location=europe-west3
```

Look for `lastAttemptTime` / `scheduleTime` in the output. Repeat for the other 5 triggers by
substituting the trigger name.

### Running a scheduled job immediately (without waiting for its time)

```bash
gcloud scheduler jobs run devops-reports-orphan-datasets-trigger \
  --project=tefde-gcp-fastoss-dev-gke \
  --location=europe-west3
```

This fires the same trigger Cloud Scheduler would fire automatically — useful for testing or
re-running a report on demand without touching the schedule itself.

### Pausing or resuming the daily schedule

```bash
# Pause (e.g. during a maintenance window)
gcloud scheduler jobs pause devops-reports-orphan-datasets-trigger \
  --project=tefde-gcp-fastoss-dev-gke --location=europe-west3

# Resume
gcloud scheduler jobs resume devops-reports-orphan-datasets-trigger \
  --project=tefde-gcp-fastoss-dev-gke --location=europe-west3
```

---

## 2. Manual runs

### Via `gcloud`

```bash
gcloud run jobs execute devops-reports-commit-drift \
  --project=tefde-gcp-fastoss-dev-gke \
  --region=europe-west3
```

Replace the job name with any of the 6 from the table above. This is the most reliable way to
trigger a report manually, since it works from any machine with `gcloud` and the right
permissions — no network restrictions apply.

---

## 3. Changing the scheduled time

The schedule is defined in Terraform, in `TEF remediation/Terraform/scheduler.tf`, as a small
set of constants:

```hcl
locals {
  scheduler_time_zone = "Europe/Berlin"

  schedule_orphan_datasets = "0 5 * * *"   # 05:00
  schedule_env_drift       = "10 5 * * *"  # 05:10
  schedule_commit_drift    = "20 5 * * *"  # 05:20
  schedule_file_drift      = "30 5 * * *"  # 05:30
  schedule_env_drift_test  = "40 5 * * *"  # 05:40
  schedule_env_drift_dev   = "50 5 * * *"  # 05:50
}
```

Each value is a standard cron expression: `minute hour day month weekday`. For example, to move
`commit_drift` to 07:00 instead of 05:20, change:
```hcl
schedule_commit_drift = "0 7 * * *"
```

### To apply the change (recommended — keeps Terraform state correct)

```bash
cd "TEF remediation/Terraform"
terraform plan    # confirm only the changed scheduler job shows as "to change"
terraform apply
```

### Quick one-off change without editing code (not recommended for permanent changes)

```bash
gcloud scheduler jobs update http devops-reports-commit-drift-trigger \
  --project=tefde-gcp-fastoss-dev-gke \
  --location=europe-west3 \
  --schedule="0 7 * * *"
```

This works immediately but creates **drift** between the live schedule and what's defined in
Terraform — the next `terraform apply` will silently revert it back to whatever is in
`scheduler.tf`. Always follow up by updating the code to match, or only use this for temporary
testing.

### Common cron patterns

| Schedule | Cron expression |
|---|---|
| Daily at 05:00 | `0 5 * * *` |
| Every 6 hours | `0 */6 * * *` |
| Weekdays only, 08:00 | `0 8 * * 1-5` |
| Weekly, Monday 06:00 | `0 6 * * 1` |

---

## 4. Checking results

### BigQuery — execution history

```sql
SELECT execution_id, report_type, execution_ts, status, triggered_by, duration_seconds, gcs_path
FROM `tefde-gcp-fastoss-dev.devops_reports.executions`
ORDER BY execution_ts DESC
LIMIT 20;
```

### GCS — CSV outputs

Browse `gs://tefde-gcp-fastoss-dev-gcs-devops-reports/` in the Cloud Console, or via:
```bash
gsutil ls gs://tefde-gcp-fastoss-dev-gcs-devops-reports/
```

### Looker Studio — dashboards

Connect a Looker Studio data source to the `devops_reports` dataset (project
`tefde-gcp-fastoss-dev`), or use one of the prebuilt queries in `looker_sql/`. No service
account key is required — Looker Studio uses your own Google identity.

---

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Job fails immediately with `Secret ... not found or has no versions` | The `gitlab-token` secret has no value loaded yet | `gcloud secrets versions add gitlab-token --project=tefde-gcp-fastoss-dev-gke --data-file=- <<< "YOUR_GITLAB_PAT"` |
| Scheduled run never seems to fire / fails silently | Grant #11 (`roles/iam.serviceAccountTokenCreator` for the Cloud Scheduler service agent) hasn't been applied yet by the TEF IAM Team | Ask the IAM Team to confirm Grant #11 in `IAM_admin_instructions.md` is in place |
| Job fails with a permission/403 error | One of the IAM grants in `IAM_admin_instructions.md` is missing | Ask the TEF IAM Team to verify the relevant grant (currently 12 grants documented) |
| env_drift `executions` rows show `status = skipped` for some repos | Expected — repos without a `production` branch (e.g. staging/demo projects) are skipped cleanly; not an error | No action needed; monitor `status = failed` rows instead |
| Need to know which report ran most recently | — | Check the BigQuery query above, or `gcloud run jobs executions list --job=<job-name> --project=tefde-gcp-fastoss-dev-gke --region=europe-west3` |
