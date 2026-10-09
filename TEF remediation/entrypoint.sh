#!/bin/bash
set -euo pipefail

# JSON logging helper — outputs Cloud Logging-compatible JSON to stdout.
# Escapes backslashes first, then double quotes, so the output is valid JSON
# without spawning a subprocess on every call.
log_json() {
  local severity="$1"
  local message="${2//\\/\\\\}"
  message="${message//\"/\\\"}"
  printf '{"severity":"%s","message":"%s"}\n' "$severity" "$message"
}

# Auto-generate EXECUTION_ID if not supplied by the caller.
# Uses Python's uuid module — no dependency on uuidgen (not in python:3.11-slim).
if [[ -z "${EXECUTION_ID:-}" ]]; then
  EXECUTION_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
  export EXECUTION_ID
fi

REPORT_TYPE="${1:-}"
if [[ -z "$REPORT_TYPE" ]]; then
    log_json "ERROR" "Usage: run-report <report_type> [args...]"
    log_json "ERROR" "Valid report types: orphan_datasets, env_drift, commit_drift, file_drift, dataset_mapping, bq_structure"
    exit 1
fi
shift

SCRIPTS_DIR="/app/scripts"

# ---------------------------------------------------------------------------
# Shared clone helper — fetches PAT from Secret Manager and clones all repos.
# Usage: clone_repos <workspace_root> <gitlab_base_url>
# Requires env vars: GCP_PROJECT, and optionally GITLAB_TOKEN_SECRET_ID.
# ---------------------------------------------------------------------------
clone_repos() {
    local workspace_root="$1"
    local gitlab_base_url="$2"

    mkdir -p "$workspace_root"
    log_json "INFO" "Cloning group repos to $workspace_root"

    local branch_arg=()
    if [[ -n "${CLONE_BRANCH:-}" ]]; then
        branch_arg=(--branch "$CLONE_BRANCH")
        log_json "INFO" "Cloning branch: $CLONE_BRANCH"
    fi

    python3 "$SCRIPTS_DIR/clone_fastoss_b.py" \
        --target-dir "$workspace_root" \
        --gitlab-base-url "$gitlab_base_url" \
        --clone-protocol https \
        --skip-workspace \
        --gcp-project "${GCP_PROJECT:?GCP_PROJECT must be set}" \
        --secret-id "${GITLAB_TOKEN_SECRET_ID:-gitlab-token}" \
        "${branch_arg[@]}"
}

case "$REPORT_TYPE" in

    orphan_datasets)
        WORKSPACE_ROOT="${REPO_ROOT:-/workspace/repos/fastossb}"
        SUBGROUP="${SUBGROUP:-ndl_core}"
        GITLAB_BASE_URL="${GITLAB_BASE_URL:-https://dot-portal.de.pri.o2.com/gitlab}"

        clone_repos "$WORKSPACE_ROOT" "$GITLAB_BASE_URL"

        exec python3 "$SCRIPTS_DIR/unmatched_bq_datasets_report.py" \
            --workspace-root "$WORKSPACE_ROOT" \
            --subgroup "$SUBGROUP" \
            "$@"
        ;;

    env_drift)
        WORKSPACE_ROOT="${REPO_ROOT:-/workspace/repos/fastossb}"
        SUBGROUP="${SUBGROUP:-ndl_core}"
        GITLAB_BASE_URL="${GITLAB_BASE_URL:-https://dot-portal.de.pri.o2.com/gitlab}"

        clone_repos "$WORKSPACE_ROOT" "$GITLAB_BASE_URL"

        SUBGROUP_ROOT="$WORKSPACE_ROOT/$SUBGROUP"
        if [[ ! -d "$SUBGROUP_ROOT" ]]; then
            log_json "ERROR" "Subgroup directory not found after clone: $SUBGROUP_ROOT"
            exit 1
        fi

        # Parse --reporting-project and other args forwarded to the Python script.
        # These are needed for the job-level summary BQ row written at the end.
        _REPORTING_PROJECT="${GCP_PROJECT:-}"
        _TARGET_ENV="prod"
        _GIT_REF=""
        _SOURCE_MODE="branch"
        _args=("$@")
        for _i in "${!_args[@]}"; do
            case "${_args[$_i]}" in
                --reporting-project) _REPORTING_PROJECT="${_args[$((_i+1))]}" ;;
                --target-env)        _TARGET_ENV="${_args[$((_i+1))]}" ;;
                --git-ref)           _GIT_REF="${_args[$((_i+1))]}" ;;
                --source-mode)       _SOURCE_MODE="${_args[$((_i+1))]}" ;;
            esac
        done

        # Job-level counters for the summary row.
        _JOB_START_TS=$(date +%s)
        _repos_total=0
        _repos_no_git=0
        _repos_excluded=0

        # Cap concurrency — running every repo at once exhausts container memory
        # once the subgroup grows past a handful of repos (OOM-killed processes,
        # no clean error). Override via the ENV_DRIFT_MAX_PARALLEL env var.
        MAX_PARALLEL="${ENV_DRIFT_MAX_PARALLEL:-5}"
        log_json "INFO" "Phase 2: running env_drift for each repo in $SUBGROUP_ROOT (parallel, max $MAX_PARALLEL at a time)"
        WORK_TMPDIR=$(mktemp -d)
        # Clean up temp dir on any exit — including signals and set -e triggers.
        trap 'rm -rf "$WORK_TMPDIR"' EXIT
        pids=()

        for repo_path in "$SUBGROUP_ROOT"/*/; do
            [[ -d "$repo_path" ]] || continue
            project_name=$(basename "$repo_path")
            _repos_total=$((_repos_total + 1))

            if [[ ! -d "$repo_path/.git" ]]; then
                _repos_no_git=$((_repos_no_git + 1))
                log_json "WARNING" "env_drift: skipping $project_name — no .git directory (clone failed?)"
                continue
            fi

            # Skip repos matching any pattern in EXCLUDE_REPOS (space-separated, glob supported).
            # Uses bash case for glob matching so patterns like 'demo_*' work.
            _excluded=0
            for _pat in ${EXCLUDE_REPOS:-}; do
                case "$project_name" in
                    $_pat) _excluded=1; break ;;
                esac
            done
            if [[ $_excluded -eq 1 ]]; then
                _repos_excluded=$((_repos_excluded + 1))
                log_json "INFO" "env_drift: skipping excluded repo $project_name (matches EXCLUDE_REPOS)"
                continue
            fi

            # Throttle: wait for a free slot before launching another repo.
            # "|| true" prevents set -e from triggering when the job we waited
            # on exited non-zero — failures are handled via the .exit file, not here.
            while [[ "$(jobs -rp | wc -l)" -ge "$MAX_PARALLEL" ]]; do
                wait -n || true
            done

            (
                # Fresh EXECUTION_ID per repo so each product gets its own audit row.
                EXECUTION_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
                export EXECUTION_ID
                log_json "INFO" "env_drift: $project_name (execution_id=$EXECUTION_ID)"
                # Capture exit code explicitly — do not rely on set -e inside the
                # subshell, which would exit before the .exit file is written.
                rc=0
                python3 "$SCRIPTS_DIR/generate_code_environment_drift_report.py" \
                    --project-name "$project_name" \
                    --repo-path "$repo_path" \
                    "$@" || rc=$?
                echo "$rc" > "$WORK_TMPDIR/$project_name.exit"
            ) &
            pids+=($!)
        done

        # || true prevents set -e from triggering on a non-zero wait exit code
        # before the exit-file loop has had a chance to run.
        wait "${pids[@]}" || true

        _repos_launched=0
        _repos_success=0
        _repos_failed=0
        for exit_file in "$WORK_TMPDIR"/*.exit; do
            [[ -f "$exit_file" ]] || continue
            _repos_launched=$((_repos_launched + 1))
            code=$(cat "$exit_file")
            if [[ "$code" == "0" ]]; then
                _repos_success=$((_repos_success + 1))
            else
                _repos_failed=$((_repos_failed + 1))
                log_json "WARNING" "env_drift failed for $(basename "$exit_file" .exit)"
            fi
        done

        # Determine overall job status for the summary row.
        if [[ $_repos_failed -gt 0 ]]; then
            _job_status="failed"
        elif [[ $_repos_no_git -gt 0 ]]; then
            _job_status="success_with_warnings"
        else
            _job_status="success"
        fi

        _JOB_DURATION=$(( $(date +%s) - _JOB_START_TS ))
        _JOB_EXEC_ID="${CLOUD_RUN_EXECUTION:-$(python3 -c 'import uuid; print(uuid.uuid4())')}"

        log_json "INFO" "env_drift summary: total=$_repos_total no_git=$_repos_no_git excluded=$_repos_excluded launched=$_repos_launched success=$_repos_success failed=$_repos_failed status=$_job_status"

        # Write job-level summary row to BQ so the dashboard can display overall
        # run status, repo counts, and warnings about skipped repos.
        python3 - <<PYEOF || log_json "WARNING" "Failed to write job summary row to BQ — dashboard will not reflect this run"
import sys
from datetime import datetime, timezone
from google.cloud import bigquery

bq = bigquery.Client(project="${_REPORTING_PROJECT}", location="europe-west3")
row = {
    "execution_id":     "${_JOB_EXEC_ID}",
    "report_type":      "env_drift",
    "project_name":     "_job_summary",
    "execution_ts":     datetime.now(timezone.utc).isoformat(),
    "environment":      "${_TARGET_ENV}",
    "git_ref":          "${_GIT_REF}" or None,
    "source_mode":      "${_SOURCE_MODE}",
    "triggered_by":     "${TRIGGERED_BY:-manual}",
    "status":           "${_job_status}",
    "duration_seconds": ${_JOB_DURATION},
    "gcs_path":         None,
    "repos_total":      ${_repos_total},
    "repos_launched":   ${_repos_launched},
    "repos_success":    ${_repos_success},
    "repos_failed":     ${_repos_failed},
}
errors = bq.insert_rows_json(
    "${_REPORTING_PROJECT}.devops_reports.executions", [row]
)
if errors:
    print(f"BQ insert errors: {errors}", file=sys.stderr)
    sys.exit(1)
PYEOF

        if [[ $_repos_failed -gt 0 ]]; then
            log_json "ERROR" "$_repos_failed repo(s) failed in env_drift"
            exit 1
        fi
        log_json "INFO" "env_drift completed for all repos in $SUBGROUP"
        ;;

    commit_drift)
        WORKSPACE_ROOT="${REPO_ROOT:-/workspace/repos/fastossb}"
        SUBGROUP="${SUBGROUP:-ndl_core}"
        GITLAB_BASE_URL="${GITLAB_BASE_URL:-https://dot-portal.de.pri.o2.com/gitlab}"

        clone_repos "$WORKSPACE_ROOT" "$GITLAB_BASE_URL"

        exec python3 "$SCRIPTS_DIR/report_branch_discrepancies_by_commit.py" \
            --root "$WORKSPACE_ROOT/$SUBGROUP" \
            --exclude-repos "${EXCLUDE_REPOS:-}" \
            "$@"
        ;;

    file_drift)
        WORKSPACE_ROOT="${REPO_ROOT:-/workspace/repos/fastossb}"
        SUBGROUP="${SUBGROUP:-ndl_core}"
        GITLAB_BASE_URL="${GITLAB_BASE_URL:-https://dot-portal.de.pri.o2.com/gitlab}"

        clone_repos "$WORKSPACE_ROOT" "$GITLAB_BASE_URL"

        exec python3 "$SCRIPTS_DIR/report_branch_discrepancies_by_content.py" \
            --root "$WORKSPACE_ROOT/$SUBGROUP" \
            --exclude-repos "${EXCLUDE_REPOS:-}" \
            "$@"
        ;;

    dataset_mapping)
        WORKSPACE_ROOT="${REPO_ROOT:-/workspace/repos/fastossb}"
        SUBGROUP="${SUBGROUP:-ndl_core}"
        GITLAB_BASE_URL="${GITLAB_BASE_URL:-https://dot-portal.de.pri.o2.com/gitlab}"

        clone_repos "$WORKSPACE_ROOT" "$GITLAB_BASE_URL"

        exec python3 "$SCRIPTS_DIR/generate_dataset_mapping.py" \
            --workspace-root "$WORKSPACE_ROOT" \
            --subgroup       "$SUBGROUP" \
            "$@"
        ;;

    bq_structure)
        WORKSPACE_ROOT="${REPO_ROOT:-/workspace/repos/fastossb}"
        SUBGROUP="${SUBGROUP:-ndl_core}"
        GITLAB_BASE_URL="${GITLAB_BASE_URL:-https://dot-portal.de.pri.o2.com/gitlab}"
        MAPPING_FILE="/tmp/dataset_repo_map.json"

        clone_repos "$WORKSPACE_ROOT" "$GITLAB_BASE_URL"

        _mapping_args=(
            --workspace-root "$WORKSPACE_ROOT"
            --subgroup       "$SUBGROUP"
            --local-output   "$MAPPING_FILE"
        )
        if [[ -n "${REPORTS_GCS_BUCKET:-}" ]]; then
            _mapping_args+=(--gcs-output "gs://${REPORTS_GCS_BUCKET}/dataset-mapping/dataset_repo_map.json")
        fi
        python3 "$SCRIPTS_DIR/generate_dataset_mapping.py" "${_mapping_args[@]}"

        exec python3 "$SCRIPTS_DIR/compare_bq_structure.py" \
            --mapping-file "$MAPPING_FILE" \
            "$@"
        ;;

    *)
        log_json "ERROR" "Unknown report type: $REPORT_TYPE. Valid types: orphan_datasets, env_drift, commit_drift, file_drift, dataset_mapping, bq_structure"
        exit 1
        ;;
esac
