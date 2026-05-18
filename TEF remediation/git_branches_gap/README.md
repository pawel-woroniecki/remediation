# Branch Drift Reports

Two types of branch drift analysis, each with a **Python script** (Cloud Run) and the original **PowerShell scripts** (local dev use).

---

## Comparison Modes

| Method | What it answers | Best for |
|---|---|---|
| **Commit-based** (`by_commit`) | Which commits exist on one branch but not the other? | Release-flow tracking, deployment lag, branch process audit |
| **File-content `merge_base`** (`by_content --compare-mode merge_base`) | What changed on the right branch since the common ancestor? | GitLab-style compare, branch change-set review |
| **File-content `direct`** (`by_content --compare-mode direct`) | Which files are actually different between branch tips right now? | Real branch alignment check |

---

## Python Scripts (Cloud Run)

### `report_branch_discrepancies_by_commit.py`

Generates commit-based drift reports across `master`, `test`, and `production` branches.

#### Outputs

Each run writes to three destinations:

**Local CSV files** (under `--output-dir`, folder `commit_drift_<date>`):

| File | Contents |
|---|---|
| `commit_counts_<date>.csv` | Commit drift matrix per repo × direction |
| `file_counts_<date>.csv` | File drift matrix per repo × direction |
| `details_<date>.csv` | Evidence ledger: one row per repo × commit × file |
| `totals_<date>.csv` | KPI totals per repo × direction |

**GCS** — all CSVs uploaded to `gs://<gcs-bucket>/<gcs-prefix>/<execution_id>/commit_drift_<date>/`.

**BigQuery** (`devops_reports`):

| Table | Contents |
|---|---|
| `branch_drift_kpis` | One row per repo × direction (`drift_type = 'commit'`); partitioned by `run_date` |
| `branch_drift_evidence` | Individual commits and files; partitioned by `run_date` |
| `executions` | Run outcome (`triggered_by`, `duration_seconds`, `status`, `gcs_path`) |

#### Parameters

| Argument | Required | Default | Description |
|---|---|---|---|
| `--root` | yes | — | Directory containing cloned repos |
| `--gcp-project` | yes | — | GCP project ID |
| `--reporting-project` | no | `--gcp-project` | GCP project for `devops_reports` dataset |
| `--gcs-bucket` | **yes** | — | GCS bucket for CSV upload. **Required** — omitting it raises an error. |
| `--gcs-prefix` | no | `branch-drift/commit` | GCS path prefix |
| `--date-tag` | no | today | Date label for output files |
| `--output-dir` | no | `./outputs` | Local output root |

#### Example

```bash
python report_branch_discrepancies_by_commit.py \
  --root /workspace/repos/fastossb/ndl_core \
  --gcp-project tefde-gcp-fastoss-dev-gke \
  --reporting-project tefde-gcp-fastoss-dev \
  --gcs-bucket tefde-gcp-fastoss-dev-gcs-devops-reports
```

---

### `report_branch_discrepancies_by_content.py`

Generates file-content drift reports across `master`, `test`, and `production` branches.

#### Outputs

**Local CSV files** (under `--output-dir`, folder `file_drift_<date>_<compare_mode>`):

| File | Contents |
|---|---|
| `file_counts_<date>.csv` | File drift matrix per repo × direction |
| `details_<date>.csv` | Evidence ledger: one row per repo × file |
| `totals_<date>.csv` | KPI totals per repo × direction |

**GCS** — all CSVs uploaded to `gs://<gcs-bucket>/<gcs-prefix>/<execution_id>/file_drift_<date>_<compare_mode>/`.

**BigQuery** (`devops_reports`):

| Table | Contents |
|---|---|
| `branch_drift_kpis` | One row per repo × direction (`drift_type = 'content'`); partitioned by `run_date` |
| `branch_drift_evidence` | Individual files and change types; partitioned by `run_date` |
| `executions` | Run outcome (`triggered_by`, `duration_seconds`, `status`, `gcs_path`) |

#### Parameters

| Argument | Required | Default | Description |
|---|---|---|---|
| `--root` | yes | — | Directory containing cloned repos |
| `--gcp-project` | yes | — | GCP project ID |
| `--reporting-project` | no | `--gcp-project` | GCP project for `devops_reports` dataset |
| `--compare-mode` | no | `merge_base` | `merge_base` or `direct` |
| `--gcs-bucket` | **yes** | — | GCS bucket for CSV upload. **Required** — omitting it raises an error. |
| `--gcs-prefix` | no | `branch-drift/content` | GCS path prefix |
| `--date-tag` | no | today | Date label for output files |
| `--output-dir` | no | `./outputs` | Local output root |

#### Example

```bash
python report_branch_discrepancies_by_content.py \
  --root /workspace/repos/fastossb/ndl_core \
  --gcp-project tefde-gcp-fastoss-dev-gke \
  --reporting-project tefde-gcp-fastoss-dev \
  --gcs-bucket tefde-gcp-fastoss-dev-gcs-devops-reports \
  --compare-mode direct
```

---

## PowerShell Scripts (local dev only)

These scripts are retained for local developer use. They do **not** write to BigQuery or GCS.

| Script | Purpose |
|---|---|
| `sync_remote_branches.ps1` | Fetch and force-align local branches to remote |
| `report_branch_discrepancies_by_commit.ps1` | Commit-based drift report (CSV output only) |
| `report_branch_discrepancies_by_content.ps1` | File-content drift report (CSV output only) |
| `run_branch_discrepancy_workflow_by_commit.ps1` | Convenience wrapper: sync + commit report |
| `run_branch_discrepancy_workflow_by_content.ps1` | Convenience wrapper: sync + content report |
| `compare_branch_discrepancy_reports.ps1` | Compare two report dates |
| `summarize_branch_discrepancies_for_exec.ps1` | Executive KPI summary |
| `report_master_to_production_gap.ps1` | Gap between any two branches |
| `aggregate_branch_discrepancies_by_domain_month.ps1` | Monthly aggregation by domain |

See the PowerShell script headers for parameter details.

---

## Severity Thresholds

### Commit-based

| Severity | Unique commits |
|---|---|
| `none` | 0 |
| `low` | 1–5 |
| `medium` | 6–20 |
| `high` | > 20 |

### File-content-based

| Severity | Unique files |
|---|---|
| `none` | 0 |
| `low` | 1–10 |
| `medium` | 11–50 |
| `high` | > 50 |

---

## Environment Variables

| Variable | Description |
|---|---|
| `EXECUTION_ID` | Auto-generated by `entrypoint.sh` if not set. Can be overridden. |
| `TRIGGERED_BY` | Identity of the user who triggered the run; injected by the UI from the IAP header. Defaults to `"ui"`. |
| `OUTPUT_DIR` | Fallback for `--output-dir` |
