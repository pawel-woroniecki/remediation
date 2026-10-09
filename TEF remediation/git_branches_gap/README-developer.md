# Developer Guide — Branch Drift Scripts

This document covers the internal design of both branch drift Python scripts:

- [`report_branch_discrepancies_by_content.py`](#file-content-drift-script) — compares file content between branches
- [`report_branch_discrepancies_by_commit.py`](#commit-based-drift-script) — compares commit history between branches

For operational use (parameters, examples, outputs) see [README.md](README.md).

---

# File-Content Drift Script

## `report_branch_discrepancies_by_content.py`

This script explains the internal design of the file-content branch drift script.
For operational use (parameters, examples, outputs) see [README.md](README.md).

---

## Purpose

The script compares file content across three branches — `master`, `test`, and
`production` — for every Git repository under a given root directory.
It answers: **"Which files look different between branch X and branch Y right now?"**

This is distinct from commit-based drift (`report_branch_discrepancies_by_commit.py`),
which answers "Which commits exist on one branch but not the other?" The two
approaches can disagree: a file may differ between branches even when no unique
commits exist (e.g. after a squash merge), and unique commits may exist without
any visible file difference (e.g. a revert).

---

## High-Level Flow

```
CLI args
   │
   ▼
for each repo:
   for each of 6 branch-pair directions:
      get_content_diff()          ← git diff --name-status
         │
         ├─ diff_rows             ← one row per changed file (file_path, raw_change_type)
         │
         └─ for each file:
               get_file_metadata() ← git log (last author, commit sha, date)
                                     results cached across repos and directions
   │
   ▼
write_csv()                       ← local CSV files
upload_to_gcs()                   ← GCS bucket
write_to_bigquery()               ← branch_drift_evidence, branch_drift_kpis, executions
```

---

## Key Constants

### `DISCREPANCY_DEFS`

Defines the 6 branch-pair directions the script checks. Each entry has:

| Field | Meaning |
|---|---|
| `name` | Unique key stored in BQ `branch_drift_evidence.discrepancy`. **Must match what `file_drift_report.sql` constructs** (see Join Key Convention below). |
| `left` | Base / reference branch (prefixed `origin/`) |
| `right` | Branch being compared against the base |

Convention: the `name` is `{right_branch}_not_in_{left_branch}`, using the full
branch name (not an abbreviation). Example: `production_not_in_test`, not `prod_not_in_test`.

> **Important**: the Looker Studio SQL view (`file_drift_report.sql`) constructs
> the JOIN key as `CONCAT(right_branch_name, '_not_in_', left_branch_name)` from
> the `origin/X` branch names stored in `branch_drift_kpis`. The `name` in
> `DISCREPANCY_DEFS` **must match this pattern exactly** or the JOIN silently
> returns null for `files_added/modified/deleted`. This mismatch was the cause
> of a historical bug (fixed commit `309493f`).

### `CHANGE_TYPE_MAP`

Maps raw `git diff --name-status` single-character codes to human-readable
`difference_type` values stored in the CSV evidence file.
The raw code (`A`, `M`, `D`, `R100`, etc.) is also stored in BQ as `change_type`
and is what the dashboard uses to count `files_added / modified / deleted`.

| Git code | Meaning | BQ `change_type` | Dashboard bucket |
|---|---|---|---|
| `A` | File exists only in right branch | `A` | `files_added` |
| `M` | Same file, different content | `M` | `files_modified` |
| `D` | File deleted in right branch | `D` | `files_deleted` |
| `R`, `C`, `T`, `U`, `X` | Renamed / copied / other | raw code | `files_other` |

---

## Key Functions

### `get_content_diff(repo_path, left, right, compare_mode)`

The core comparison. Returns a list of `{file_path, raw_change_type, difference_type}` dicts.

**Two modes** controlled by `--compare-mode`:

- **`merge_base` (default)**: runs `git diff --name-status <merge_base> <right>`.
  The merge base is the common ancestor of `left` and `right`. This matches what
  GitLab's "Compare" view shows — only changes introduced on the right branch
  since the branches diverged.

- **`direct`**: runs `git diff --name-status <left> <right>`.
  Compares the two branch tips directly. Shows all files that are currently
  different, regardless of when or how the difference was introduced.

Use `direct` to answer "are these branches aligned right now?" and `merge_base`
to answer "what did someone change on this branch since it forked?"

### `get_file_metadata(repo_path, branch, file_path, cache)`

Runs two `git log` calls per file on the right branch:
1. `--diff-filter=A --follow -n 1` — finds the commit that first added the file.
2. `-n 1` — finds the most recent commit that touched the file.

Results are stored in `metadata_cache` (a `dict` keyed by `repo|branch|file_path`)
and shared across all 6 directions and all repos. This avoids redundant git calls
when the same file appears in multiple directions (which is common).

The metadata is written to the evidence table alongside the file diff so that
the dashboard can show who last changed a drifting file and when.

### `get_merge_base(repo_path, left, right)`

Thin wrapper around `git merge-base left right`. Returns the commit SHA of the
common ancestor, or `None` if git fails (e.g. branches have no shared history).
A `None` result causes `get_content_diff` to return an empty list and the
direction is skipped.

### `content_severity(unique_files)`

Maps a file count to a severity string written to `branch_drift_kpis.severity`:

| Threshold | Severity |
|---|---|
| 0 | `none` |
| 1–10 | `low` |
| 11–50 | `medium` |
| > 50 | `high` |

---

## Data Written to BigQuery

Three tables are written per run, in this order (evidence before kpis before executions):

### `branch_drift_evidence`

One row per repo × direction × file. Key columns:

| Column | Source | Notes |
|---|---|---|
| `execution_id` | env var `EXECUTION_ID` | Links all tables for the same run |
| `repo` | directory name | Name of the cloned git repo |
| `discrepancy` | `DISCREPANCY_DEFS[n]["name"]` | Join key — must match SQL view convention |
| `file_path` | `git diff` output | Relative path within the repo |
| `change_type` | raw git status code (`A`/`M`/`D`/`R100` etc.) | Used by dashboard to count `files_added` etc. |
| `commit_sha` | `git log -n 1` on right branch | Last commit that touched the file |
| `commit_date` | same | ISO 8601 timestamp |
| `author` | same | Display name of the last committer |
| `problem_statement` | template string | Human-readable description of the discrepancy |

### `branch_drift_kpis`

One row per repo × direction. Key columns:

| Column | Source | Notes |
|---|---|---|
| `unique_files` | `len({r["file_path"] for r in diff_rows})` | Count of distinct drifting files |
| `severity` | `content_severity(unique_files)` | `none` / `low` / `medium` / `high` |
| `comparison_mode` | `--compare-mode` arg | `merge_base` or `direct` |
| `drift_type` | hardcoded `"content"` | Distinguishes from commit-based rows |
| `left_branch` / `right_branch` | `DISCREPANCY_DEFS` | Full `origin/X` form |

### `executions`

One row per script run. Written last (after evidence and kpis) so that a
partial failure does not leave an `executions` row that would make the run
appear successful. If BQ writes for evidence or kpis fail, the exception
propagates and the `executions` row is written with `status = "failed"`.

---

## Idempotency Guard

Before writing to BigQuery, `execution_id_exists()` queries `executions` for
the current `execution_id` within the last 2 days. If found, BQ writes are
skipped entirely. This protects against Cloud Run retry storms where the same
job execution is re-triggered before the previous run's data has landed.

The `EXECUTION_ID` env var is injected by `entrypoint.sh` at container start
using a UUID. It is the same value across all three BQ writes within a single run.

---

## Error Handling

The entire `main()` body is wrapped in a `try/except`. On any unhandled exception:

1. A `status = "failed"` row is written to `executions` (best-effort — a second
   exception here is swallowed).
2. The original exception is re-raised, which causes the Cloud Run Job to exit
   non-zero and report the run as failed in the GCP console.

Per-direction errors (missing branch, `git diff` failure) are handled inline and
recorded as `status = "missing_branch"` or `status = "error"` in `branch_drift_kpis`.
They do not abort the run.

---

## Join Key Convention (critical for dashboard correctness)

The `file_drift_report.sql` Looker Studio view joins `branch_drift_kpis` with
`branch_drift_evidence` using:

```sql
ea.discrepancy = CONCAT(
    REGEXP_EXTRACT(ks.right_branch, r'origin/(.+)'),
    '_not_in_',
    REGEXP_EXTRACT(ks.left_branch,  r'origin/(.+)')
)
```

For `right_branch = origin/production`, `left_branch = origin/test`, this produces:
`production_not_in_test`.

The `name` field in `DISCREPANCY_DEFS` must equal this constructed string.
Using any abbreviation (e.g. `prod_not_in_test`) causes the LEFT JOIN to miss
and `files_added/modified/deleted` will appear null in the dashboard, even though
the evidence rows exist in BigQuery.

---

## Adding a New Branch Direction

1. Add an entry to `DISCREPANCY_DEFS` with `name = "{right}_not_in_{left}"`
   using the full branch name (without the `origin/` prefix).
2. Add a corresponding column to `file_count_rows` using `_val("<name>", "unique_files")`.
3. No changes needed in the SQL view or dashboard — new directions are picked up
   automatically via the dynamic JOIN key.

---

## Local Development

To run outside Cloud Run (no GCS upload, writing CSVs only):

```bash
export EXECUTION_ID=local-test-001
export TRIGGERED_BY=developer

python report_branch_discrepancies_by_content.py \
  --root /path/to/cloned-repos \
  --gcp-project tefde-gcp-fastoss-dev \
  --reporting-project tefde-gcp-fastoss-dev \
  --gcs-bucket to-be-added-later \   # triggers ValueError; skip BQ flag not available
  --compare-mode direct \
  --output-dir /tmp/file-drift-test
```

To avoid GCS and BQ writes entirely during local testing, you can temporarily
comment out the `upload_to_gcs()` and `write_to_bigquery()` calls in `main()`.

---

# Commit-Based Drift Script

## `report_branch_discrepancies_by_commit.py`

## Purpose

Identifies commits that exist on one branch but not on another across
`master`, `test`, and `production`. Where the content script answers
"which files look different?", this script answers "which commits caused
the difference, and who made them?"

The two scripts are complementary: content drift can exist without unique
commits (squash merge, rebase) and unique commits can exist without
visible content drift (a revert).

---

## High-Level Flow

```
for each repo:
   for each of 6 branch-pair directions:
      get_detail_rows()    ← git log --no-merges --right-only --cherry-pick
                                      --name-only --pretty=format:@@@<meta>
         │
         └─ one row per repo × commit × file
   │
   ▼
write_csv()              ← commit_counts, file_counts, details, totals
upload_to_gcs()
write_to_bigquery()      ← branch_drift_evidence, branch_drift_kpis, executions
```

---

## `DISCREPANCY_DEFS`

Same structure as the content script: 6 directions across the three branches.
Note that the commit script uses abbreviated names (`prod_not_in_test` etc.)
for the `name` field. This is intentional here because the `commit_drift_report.sql`
view uses a different JOIN strategy that does not construct the key from branch
names. If you extend the SQL view, verify the join keys match.

---

## `get_detail_rows(repo_path, repo_name, left, right, discrepancy_name, problem_statement)`

The core function. Runs:

```bash
git log --no-merges --right-only --cherry-pick \
        --name-only --pretty=format:@@@%H|%aI|%an|%ae|%s \
        origin/left...origin/right
```

**What each git flag does:**

| Flag | Effect |
|---|---|
| `--no-merges` | Excludes merge commits — only shows substantive changes |
| `--right-only` | Shows only commits reachable from `right` but not `left` |
| `--cherry-pick` | Further filters to commits whose patch ID does not exist on `left` — excludes cherry-picked duplicates |
| `--name-only` | Appends the list of changed files after each commit header |
| `--pretty=format:@@@<fields>` | Custom format: commit lines start with `@@@` so the parser can distinguish them from file path lines |

**Output parsing** — the stdout mixes two line types:
- `@@@<hash>|<iso_date>|<author>|<email>|<subject>` — commit header
- `path/to/file.sql` — file changed by the current commit

The parser maintains `current_hash` state: file lines are attributed to the
most recently seen `@@@` commit header. Empty lines between commits are ignored.

**Returns**: `(rows, unique_file_count, unique_commit_count)`
- `rows`: one dict per commit × file (used for BQ evidence and CSV detail)
- `unique_file_count`: count of distinct file paths across all commits in this direction
- `unique_commit_count`: count of distinct commits that actually touch at least one file

---

## Severity Thresholds

| Unique commits | Severity |
|---|---|
| 0 | `none` |
| 1–5 | `low` |
| 6–20 | `medium` |
| > 20 | `high` |

---

## BigQuery Tables Written

Same three tables as the content script, written in the same order (evidence → kpis → executions):

| Table | Key difference vs content script |
|---|---|
| `branch_drift_evidence` | `drift_type = 'commit'`; `change_type = None` (no git diff codes); `commit_sha` and `author` are always populated |
| `branch_drift_kpis` | `drift_type = 'commit'`; `comparison_mode = 'cherry_pick_no_merges'`; both `unique_commits` and `unique_files` are populated |
| `executions` | `report_type = 'commit_drift'` |

---

## Idempotency and Error Handling

Identical to the content script: `execution_id_exists()` guard before BQ writes;
top-level `try/except` writes `status = "failed"` and re-raises.

---

## Local Development

```bash
export EXECUTION_ID=local-test-001
export TRIGGERED_BY=developer

python report_branch_discrepancies_by_commit.py \
  --root /path/to/cloned-repos \
  --gcp-project tefde-gcp-fastoss-dev \
  --reporting-project tefde-gcp-fastoss-dev \
  --gcs-bucket to-be-added-later \
  --output-dir /tmp/commit-drift-test
```
