# Scripts README

This folder contains PowerShell automation for branch refresh, discrepancy reporting, date-to-date diffing, and executive statistics generation.

## Comparison Modes Summary

| Method | What it answers | Best for | Can look bigger than real current drift? |
|---|---|---|---|
| Commit-based comparison (`report_branch_discrepancies_by_commit.ps1`) | Which commits or patches exist on one branch but not the other? | Release-flow tracking, deployment lag, branch process audit | Yes |
| File-based `merge_base` comparison (`-CompareMode merge_base`) | What changed on the right branch since the common ancestor with the left branch? | Matching GitLab compare semantics, branch change-set review | Yes |
| File-based `direct` comparison (`-CompareMode direct`) | Which files are actually different between the two branch tips right now? | Real branch alignment, deciding what still needs syncing | No |

Notes:
- Commit-based comparison is history-oriented. A file can be changed in many commits and still end up identical on both branches.
- File-based `merge_base` comparison is branch-history-relative. It may show a file even if both branch tips now contain the same content.
- File-based `direct` comparison is end-state-oriented. It is usually the best view for answering "what is really different now?".

Underlying Git commands:

- Commit-based comparison:
```powershell
git -C <repo> rev-list --no-merges --left-right --cherry-pick --count origin/production...origin/master
git -C <repo> log --no-merges --right-only --cherry-pick --name-only --pretty=format: origin/production...origin/master
git -C <repo> log --no-merges --right-only --cherry-pick --date=iso --name-only --pretty=format:'@@@%H|%ad|%an|%ae|%s' origin/production...origin/master
```

- File-based `merge_base` comparison:
```powershell
git -C <repo> merge-base origin/master origin/production
git -C <repo> diff --name-status <merge-base-sha> origin/production
```

- File-based `direct` comparison:
```powershell
git -C <repo> diff --name-status origin/master origin/production
git -C <repo> diff --name-only origin/master origin/production
```

- File metadata in detail report:
```powershell
git -C <repo> ls-tree -r --name-only origin/production -- <file-path>
git -C <repo> log --diff-filter=A --follow -n 1 --format=%H|%ad|%an|%ae|%s origin/production -- <file-path>
git -C <repo> log -n 1 --format=%H|%ad|%an|%ae|%s origin/production -- <file-path>
```

## Prerequisites

- PowerShell 5+ / PowerShell 7+
- Git CLI available in PATH
- Local clones under `c:\repos\fastossb\ndl_core`
- Access to remotes (fetch/push permissions as needed)

## Default Paths

- Repository scan root defaults to `c:\repos\fastossb\ndl_core`
- Output files default to [outputs](c:/repos/fastossb/devops-reports/outputs)
- Input-based scripts such as comparison and executive summary also default to [outputs](c:/repos/fastossb/devops-reports/outputs)

## Scripts Overview

### `sync_remote_branches.ps1`

Purpose:
- Fetches remotes and force-refreshes local repos.
- Discards local uncommitted changes.
- Aligns local `master`, `test`, `production` to `origin/*` when available.

Parameters:
- `-Root` (default: `c:\repos\fastossb\ndl_core`)
- `-DateTag` (default: current date `yyyy-MM-dd`)
- `-OutputDir` (default: `.\outputs`)

Output:
- `branch_refresh_status_<DateTag>.csv`

File purpose:
- Snapshot of refresh execution quality across repos after force-sync to remote.

Columns:
- `repo`: repository folder name.
- `status`: refresh result (`ok` or `error`).
- `notes`: extra info (for example `origin/test missing`, `origin/production missing`, or error text).

Benchmarks:
- `status`:
  - Best case: `ok` for 100% repos.
  - Base case (acceptable): `ok` for >=95% repos.
  - Risk case: any `error`.
- `notes`:
  - Best case: empty (no missing branches, no warnings).
  - Base case: only expected missing-branch notes for known repos.
  - Risk case: repeated operational errors/warnings.

Example:
```powershell
.\reports\git_branches_gap\sync_remote_branches.ps1 -Root c:\repos\fastossb\ndl_core -OutputDir .\outputs
```

---

### `report_branch_discrepancies_by_commit.ps1`

Purpose:
- Generates discrepancy reports between `master`, `test`, `production`.
- Uses patch-aware comparison (`--cherry-pick`) and excludes merge commits (`--no-merges`).

Parameters:
- `-Root` (default: `c:\repos\fastossb\ndl_core`)
- `-DateTag` (default: current date `yyyy-MM-dd`)
- `-OutputDir` (default: `.\outputs`)

Outputs:

1. `branch_discrepancy_counts_prod_master_test_no_merges_<DateTag>.csv`

File purpose:
- Commit-level divergence matrix between environment branches, patch-aware and excluding merge commits.

Columns:
- `repo`: repository folder name.
- `has_master`: whether `origin/master` exists.
- `has_test`: whether `origin/test` exists.
- `has_production`: whether `origin/production` exists.
- `master_not_in_test_commits_no_merges`: number of non-merge, patch-unique commits in `master` not in `test`.
- `test_not_in_master_commits_no_merges`: number of non-merge, patch-unique commits in `test` not in `master`.
- `prod_not_in_test_commits_no_merges`: number of non-merge, patch-unique commits in `production` not in `test`.
- `test_not_in_prod_commits_no_merges`: number of non-merge, patch-unique commits in `test` not in `production`.
- `prod_not_in_master_commits_no_merges`: number of non-merge, patch-unique commits in `production` not in `master`.
- `master_not_in_prod_commits_no_merges`: number of non-merge, patch-unique commits in `master` not in `production`.
- `N/A`: branch side missing, so comparison not possible.

Benchmarks (for each `*_commits_no_merges` column):
- Best case: `0`
- Base case (short-lived release lag): `1-5`
- Warning: `6-20`
- Critical: `>20`
- Target governance KPI: `0` in all six columns.

2. `branch_discrepancy_file_counts_prod_master_test_no_merges_<DateTag>.csv`

File purpose:
- File-level divergence matrix showing how many unique files differ by branch direction.

Columns:
- `repo`, `has_master`, `has_test`, `has_production`: same meaning as above.
- `master_files_not_in_test_no_merges`: unique file paths touched by patch-unique non-merge commits in `master` vs `test`.
- `test_files_not_in_master_no_merges`: unique file paths touched by patch-unique non-merge commits in `test` vs `master`.
- `prod_files_not_in_test_no_merges`: unique file paths touched by patch-unique non-merge commits in `production` vs `test`.
- `test_files_not_in_prod_no_merges`: unique file paths touched by patch-unique non-merge commits in `test` vs `production`.
- `prod_files_not_in_master_no_merges`: unique file paths touched by patch-unique non-merge commits in `production` vs `master`.
- `master_files_not_in_prod_no_merges`: unique file paths touched by patch-unique non-merge commits in `master` vs `production`.

Benchmarks (for each `*_files_*` column):
- Best case: `0`
- Base case (small controlled drift): `1-10`
- Warning: `11-50`
- Critical: `>50`
- KPI target: `0` for all six directions.

3. `branch_discrepancy_file_commit_lines_prod_master_test_no_merges_<DateTag>.csv`

File purpose:
- Full evidence ledger at commit+file granularity; each row is one affected file in one discrepant commit.

Columns:
- `repo`: repository folder name.
- `discrepancy`: one of
  - `prod_not_in_master`
  - `prod_not_in_test`
  - `test_not_in_master`
  - `test_not_in_prod`
  - `master_not_in_test`
  - `master_not_in_prod`
- `left_branch`: branch used as left side of `<left>...<right>` comparison.
- `right_branch`: branch used as right side (source of returned rows).
- `commit`: commit SHA that is patch-unique on `right_branch` side.
- `created_at`: commit author date.
- `author`: commit author.
- `message`: commit subject.
- `file_path`: affected file path (one row per file per commit).
- `problem_statement`: standardized text label describing discrepancy semantics.

Benchmarks:
- This is a detail/evidence file, not a KPI file.
- Best case for data volume: empty file (or 0 rows) when all branches are aligned.
- Base case: low row volume and concentrated to planned release windows.

4. `branch_discrepancy_file_totals_prod_master_test_no_merges_<DateTag>.csv`

File purpose:
- Aggregated discrepancy totals per repo and discrepancy type; primary dashboard table for trend tracking.

Columns:
- `repo`, `discrepancy`, `left_branch`, `right_branch`: as above.
- `total_file_lines`: number of rows that would appear in detailed file-commit report for this repo+discrepancy.
- `unique_files_affected`: number of unique file paths for this repo+discrepancy.
- `unique_commits`: number of unique commits for this repo+discrepancy.
- `status`:
  - `ok`: comparison executed.
  - `missing_branch`: one side branch not available.

Benchmarks:
- `unique_files_affected`:
  - Best case: `0`
  - Base case: `1-10`
  - Warning: `11-50`
  - Critical: `>50`
- `unique_commits`:
  - Best case: `0`
  - Base case: `1-5`
  - Warning: `6-20`
  - Critical: `>20`
- `status`:
  - Best case: `ok` for 100% expected pairs.
  - Risk case: `missing_branch` in core delivery repos.

Example:
```powershell
.\reports\git_branches_gap\report_branch_discrepancies_by_commit.ps1 -DateTag 2026-03-03 -OutputDir .\outputs
```

---

### `report_branch_discrepancies_by_content.ps1`

Purpose:
- Generates discrepancy reports between `master`, `test`, `production`.
- Uses GitLab-style compare semantics (`left...right` from merge base to right branch), not commit history.

Parameters:
- `-Root` (default: `c:\repos\fastossb\ndl_core`)
- `-DateTag` (default: current date `yyyy-MM-dd`)
- `-OutputDir` (default: `.\outputs`)
- `-CompareMode`
  - `merge_base` (default): GitLab-style compare from common ancestor to right branch
  - `direct`: direct branch-tip diff

Outputs:

1. `branch_discrepancy_file_counts_prod_master_test_content_<DateTag>.csv`

File purpose:
- File-level divergence matrix showing how many files on each branch differ from another branch by actual content.

Columns:
- `repo`, `has_master`, `has_test`, `has_production`: same meaning as above.
- `master_files_not_in_test_by_content`: files present only in `master` or whose content differs from `test`.
- `test_files_not_in_master_by_content`: files present only in `test` or whose content differs from `master`.
- `prod_files_not_in_test_by_content`: files present only in `production` or whose content differs from `test`.
- `test_files_not_in_prod_by_content`: files present only in `test` or whose content differs from `production`.
- `prod_files_not_in_master_by_content`: files present only in `production` or whose content differs from `master`.
- `master_files_not_in_prod_by_content`: files present only in `master` or whose content differs from `production`.

2. `branch_discrepancy_file_lines_prod_master_test_content_<DateTag>.csv`

File purpose:
- One row per discrepant file for each branch direction, based on branch-tip content only.

Columns:
- `repo`, `discrepancy`, `left_branch`, `right_branch`, `file_path`
- `raw_change_type`: raw `git diff --name-status` code.
- `difference_type`: `right_only` or `different_content`.
- `problem_statement`: standardized discrepancy description.

3. `branch_discrepancy_file_totals_prod_master_test_content_<DateTag>.csv`

File purpose:
- Aggregated discrepancy totals per repo and discrepancy type for content-based drift.

Columns:
- `repo`, `discrepancy`, `left_branch`, `right_branch`
- `total_file_rows`: total discrepant file rows for that repo+direction.
- `unique_files_affected`: unique file paths for that repo+direction.
- `right_only_files`: files that exist only on the right branch.
- `deleted_in_right_files`: files deleted on the right branch relative to the merge base.
- `renamed_in_right_files`: files renamed on the right branch.
- `copied_in_right_files`: files copied on the right branch.
- `different_content_files`: files that exist on both sides but differ in content.
- `status`: `ok`, `missing_branch`, or `error`.

Example:
```powershell
.\reports\git_branches_gap\report_branch_discrepancies_by_content.ps1 -DateTag 2026-03-03 -OutputDir .\outputs

# Direct branch-tip comparison
.\reports\git_branches_gap\report_branch_discrepancies_by_content.ps1 -DateTag 2026-03-03 -OutputDir .\outputs -CompareMode direct
```

---

### `report_branch_discrepancies_by_content_compat.ps1`

Purpose:
- Naming-compatible entrypoint for the content-based discrepancy report.
- Keeps the existing `no_merges` naming style while using file-content comparison only.

Parameters:
- `-Root` (default: `c:\repos\fastossb\ndl_core`)
- `-DateTag` (default: current date `yyyy-MM-dd`)
- `-OutputDir` (default: `.\outputs`)
- `-CompareMode` (same values as above)

Outputs:
- Same outputs as `report_branch_discrepancies_by_content.ps1`

Example:
```powershell
.\reports\git_branches_gap\report_branch_discrepancies_by_content_compat.ps1 -DateTag 2026-03-03 -OutputDir .\outputs

# Direct branch-tip comparison
.\reports\git_branches_gap\report_branch_discrepancies_by_content_compat.ps1 -DateTag 2026-03-03 -OutputDir .\outputs -CompareMode direct
```

---

### `run_branch_discrepancy_workflow_by_commit.ps1`

Purpose:
- Convenience wrapper.
- Runs refresh + no-merge discrepancy report generation in sequence.

Parameters:
- `-Root` (default: `c:\repos\fastossb\ndl_core`)
- `-DateTag` (default: current date `yyyy-MM-dd`)
- `-OutputDir` (default: `.\outputs`)

Outputs:
- All outputs from `sync_remote_branches.ps1`
- All outputs from `report_branch_discrepancies_by_commit.ps1`

Example:
```powershell
.\reports\git_branches_gap\run_branch_discrepancy_workflow_by_commit.ps1 -DateTag 2026-03-03 -OutputDir .\outputs
```

---

### `run_branch_discrepancy_workflow_by_content.ps1`

Purpose:
- Convenience wrapper.
- Runs refresh + content-based discrepancy report generation in sequence.

Parameters:
- `-Root` (default: `c:\repos\fastossb\ndl_core`)
- `-DateTag` (default: current date `yyyy-MM-dd`)
- `-OutputDir` (default: `.\outputs`)

Outputs:
- All outputs from `sync_remote_branches.ps1`
- All outputs from `report_branch_discrepancies_by_content.ps1`

Example:
```powershell
.\reports\git_branches_gap\run_branch_discrepancy_workflow_by_content.ps1 -DateTag 2026-03-03 -OutputDir .\outputs
```

---

### `run_branch_discrepancy_workflow_by_content_compat.ps1`

Purpose:
- Naming-compatible wrapper for the content-based workflow.
- Runs refresh + content-based discrepancy report generation in sequence.

Parameters:
- `-Root` (default: `c:\repos\fastossb\ndl_core`)
- `-DateTag` (default: current date `yyyy-MM-dd`)
- `-OutputDir` (default: `.\outputs`)
- `-SkipRefresh` (optional: skip `sync_remote_branches.ps1` and run reports against current local refs)
- `-CompareMode` (same values as above)

Outputs:
- All outputs from `sync_remote_branches.ps1`
- All outputs from `report_branch_discrepancies_by_content_compat.ps1`

Example:
```powershell
.\reports\git_branches_gap\run_branch_discrepancy_workflow_by_content_compat.ps1 -DateTag 2026-03-03 -OutputDir .\outputs

# Skip refresh and only generate reports from current local refs
.\reports\git_branches_gap\run_branch_discrepancy_workflow_by_content_compat.ps1 -DateTag 2026-03-03 -OutputDir .\outputs -SkipRefresh

# Skip refresh and use direct branch-tip comparison
.\reports\git_branches_gap\run_branch_discrepancy_workflow_by_content_compat.ps1 -DateTag 2026-03-03 -OutputDir .\outputs -SkipRefresh -CompareMode direct
```

---

### `compare_branch_discrepancy_reports.ps1`

Purpose:
- Compares two detailed report dates:
  - `branch_discrepancy_file_commit_lines_prod_master_test_no_merges_<Date>.csv`
- Produces summary delta and exact row-level adds/removes.

Parameters:
- `-DateOld` (default: `2026-03-02`)
- `-DateNew` (default: `2026-03-03`)
- `-InputDir` (default: `.\outputs`)
- `-OutputDir` (default: `.\outputs`)

Outputs:

1. `discrepancy_report_diff_summary_<DateOld>_vs_<DateNew>_<Timestamp>.csv`

File purpose:
- Single-row trend summary that quantifies how discrepancy evidence changed between two reporting dates.

Columns:
- `date_old`, `date_new`: compared dates.
- `rows_old`, `rows_new`: total detailed rows per date.
- `delta_rows`: `rows_new - rows_old`.
- `only_in_old`: rows present only in old report.
- `only_in_new`: rows present only in new report.
- `changed_repo_discrepancy_pairs`: count of repo+discrepancy pairs where row count changed.

Benchmarks:
- `delta_rows`:
  - Best case: `<0` (discrepancies reduced)
  - Base case: `0` (stable)
  - Risk case: `>0` (discrepancies increased)
- `changed_repo_discrepancy_pairs`:
  - Best case: `0` (no churn)
  - Base case: low single digits with known releases
  - Risk case: broad unplanned movement.

2. `discrepancy_report_diff_pairs_<DateOld>_vs_<DateNew>_<Timestamp>.csv`

File purpose:
- Pair-level trend table showing which repo+discrepancy combinations improved or regressed.

Columns:
- `repo`: repository name.
- `discrepancy`: discrepancy type.
- `count_old`: row count in old report for this pair.
- `count_new`: row count in new report for this pair.
- `delta`: `count_new - count_old`.

Benchmarks:
- `delta`:
  - Best case: negative values (reduction).
  - Base case: `0`.
  - Risk case: positive values.

3. `discrepancy_report_only_in_<DateOld>_<Timestamp>.csv`
4. `discrepancy_report_only_in_<DateNew>_<Timestamp>.csv`

File purpose:
- Row-level evidence of removals (`only_in_old`) and additions (`only_in_new`) between dates.

Columns in both:
- Same schema as `branch_discrepancy_file_commit_lines...` (`repo`, `discrepancy`, `left_branch`, `right_branch`, `commit`, `created_at`, `author`, `message`, `file_path`, `problem_statement`).
- These files represent exact row-level removals/additions between dates.

Benchmarks:
- Best case: `only_in_new` small/zero and `only_in_old` larger during cleanup cycles.
- Base case: balanced changes during active release windows.
- Risk case: persistent high `only_in_new`.

Example:
```powershell
.\reports\git_branches_gap\compare_branch_discrepancy_reports.ps1 -DateOld 2026-03-02 -DateNew 2026-03-03 -InputDir .\outputs -OutputDir .\outputs
```

---

### `summarize_branch_discrepancies_for_exec.ps1`

Purpose:
- Builds executive-level statistics (numbers only, no conclusions) for one report date.

Inputs required for `DateTag`:
- `branch_discrepancy_counts_prod_master_test_no_merges_<DateTag>.csv`
- `branch_discrepancy_file_totals_prod_master_test_no_merges_<DateTag>.csv`
- `branch_discrepancy_file_commit_lines_prod_master_test_no_merges_<DateTag>.csv`

Parameters:
- `-DateTag` (default: current date `yyyy-MM-dd`)
- `-InputDir` (default: `.\outputs`)
- `-OutputDir` (default: `.\outputs`)

Outputs:

1. `executive_summary_stats_<DateTag>_<Timestamp>.csv`

File purpose:
- One-row executive KPI snapshot for the selected date.

Columns:
- `date_tag`: report date.
- `total_repos`: distinct repos in totals file.
- `total_repo_discrepancy_pairs`: total repo+discrepancy rows.
- `pairs_ok`: rows with successful comparison.
- `pairs_with_missing_branch`: rows with missing branch status.
- `pairs_with_nonzero_files`: rows where `unique_files_affected > 0`.
- `repos_with_complete_branches`: repos with all required branches present for at least one pair.
- `repos_fully_aligned`: repos where all six discrepancy types are zero.
- `repos_with_any_discrepancy`: repos with at least one non-zero discrepancy.
- `total_detail_rows`: total rows in detail file.
- `total_unique_files_across_detail`: distinct file paths in detail file.
- `total_unique_commits_across_detail`: distinct commits in detail file.
- `min_discrepancy_commit_date`, `max_discrepancy_commit_date`: date range in detail data.
- `sum_unique_files_*`: summed unique file counts per major discrepancy class.
- `sum_commits_*`: summed commit counts per discrepancy class.

Benchmarks:
- `repos_fully_aligned / repos_with_complete_branches`:
  - Best case: `100%`
  - Base case: `>=80%`
  - Risk case: `<50%`
- `pairs_with_nonzero_files / pairs_ok`:
  - Best case: `0%`
  - Base case: `<20%`
  - Risk case: `>40%`
- `sum_commits_*`, `sum_unique_files_*`:
  - Best case: `0`
  - Trend target: decreasing over time.

2. `executive_top_repos_by_files_<DateTag>_<Timestamp>.csv`

File purpose:
- Ranking of repositories by total file-level discrepancy footprint.

Columns:
- `repo`: repository name.
- `total_unique_files`: sum of `unique_files_affected` across six discrepancy types.
- `nonzero_pairs`: number of discrepancy types with non-zero files.

Benchmarks:
- `total_unique_files`:
  - Best case: `0`
  - Base case: low double digits
  - Critical: high triple digits
- `nonzero_pairs`:
  - Best case: `0/6`
  - Risk case: `>=4/6`.

3. `executive_by_discrepancy_<DateTag>_<Timestamp>.csv`

File purpose:
- Discrepancy-type leaderboard across all repos (which branch direction contributes most drift).

Columns:
- `discrepancy`: discrepancy type.
- `repos_with_nonzero`: number of repos with non-zero files for this discrepancy.
- `sum_unique_files`: total unique files (summed across repos).
- `sum_unique_commits`: total unique commits (summed across repos).

Benchmarks:
- Best case for all three metrics: `0`
- Base case: low values concentrated in planned promotion windows.
- Risk case: sustained high values in `prod_not_in_test` or `prod_not_in_master`.

4. `executive_top_contributors_raw_<DateTag>_<Timestamp>.csv`

File purpose:
- Contributor distribution using raw author strings exactly as stored in commits.

Columns:
- `author`: raw author value from commits.
- `rows`: number of detail rows associated with author.
- `unique_commits`: distinct commits by author.
- `unique_files`: distinct files by author.

Benchmarks:
- No universal “best value”; use for concentration analysis.
- Practical signal: very high concentration in a few authors may indicate process bottlenecks or specialized hotfix ownership.

5. `executive_top_contributors_normalized_<DateTag>_<Timestamp>.csv`

File purpose:
- Contributor distribution after normalizing author labels (combines `(External)` variants).

Columns:
- Same as raw contributors.
- `author` normalized by removing trailing ` (External)`.

Benchmarks:
- Same interpretation as raw contributors.
- Prefer this file for management reporting to avoid split identities.

6. `executive_message_signals_<DateTag>_<Timestamp>.csv`

File purpose:
- Message-pattern telemetry (frequency of workflow signals in discrepant commits).

Columns:
- `signal`: searched text pattern (`cherry-pick`, `Merge branch`, `revert`, `patch:`, `minor:`, `major:`).
- `row_count`: number of detail rows whose commit message contains the signal.

Benchmarks:
- No absolute threshold; evaluate trends date-over-date.
- Risk indicator: rising `cherry-pick`/`revert` counts together with high discrepancy totals.

7. `executive_repo_alignment_status_<DateTag>_<Timestamp>.csv`

File purpose:
- Repo-level alignment status card (binary aligned/not aligned).

Columns:
- `repo`: repository name.
- `nonzero_pairs`: number of discrepancy types with non-zero files.
- `aligned`: boolean (`True` when `nonzero_pairs = 0`).

Benchmarks:
- `aligned=True`:
  - Best case: 100% repos.
  - Base case: >=80%.
  - Risk case: <50%.
- `nonzero_pairs`:
  - Best case: `0`
  - Risk case: `>=4` per repo.

Example:
```powershell
.\reports\git_branches_gap\summarize_branch_discrepancies_for_exec.ps1 -DateTag 2026-03-03 -InputDir .\outputs -OutputDir .\outputs
```

---

### `report_master_to_production_gap.ps1`

Purpose:
- Compares any two remote branches for each repo
- Defaults to `origin/master` as source and `origin/production` as target
- Highlights source-branch commits that are still waiting to reach the target branch

Parameters:
- `-Root`
  Default: auto-detected `ndl_core` root in the shared workspace
- `-Fetch`
  Optional: refresh remote refs before comparison
- `-SourceBranch`
  Default: `master`
- `-TargetBranch`
  Default: `production`
- `-Output`
  Default: `.\outputs`

Output:
- `branch_gap_report_<SourceBranch>_vs_<TargetBranch>_<Timestamp>.csv`

Example:
```powershell
.\reports\git_branches_gap\report_master_to_production_gap.ps1 -Fetch -Output .\outputs

# Compare test against production instead of master against production
.\reports\git_branches_gap\report_master_to_production_gap.ps1 -SourceBranch test -TargetBranch production -Output .\outputs
```

---

### `aggregate_branch_discrepancies_by_domain_month.ps1`

Purpose:
- Aggregates `discrepancy_domain_month_type_<DateTag>.csv`
- Produces one row per `domain` and `month_year`

Parameters:
- `-DateTag` (default: current date `yyyy-MM-dd`)
- `-InputDir` (default: `.\outputs`)
- `-OutputDir` (default: `.\outputs`)

Output:
- `discrepancy_domain_month_<DateTag>.csv`

Example:
```powershell
.\reports\git_branches_gap\aggregate_branch_discrepancies_by_domain_month.ps1 -DateTag 2026-03-03 -InputDir .\outputs -OutputDir .\outputs
```

## Notes

- These scripts use strict mode and may fail fast on malformed or missing inputs.
- `sync_remote_branches.ps1` is destructive for local uncommitted changes.
- Protected branch policies can prevent direct push operations; these scripts are designed for reporting and local alignment checks.

