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
    log_json "ERROR" "Valid report types: orphan_datasets, env_drift, commit_drift, file_drift"
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
    python3 "$SCRIPTS_DIR/clone_fastoss_b.py" \
        --target-dir "$workspace_root" \
        --gitlab-base-url "$gitlab_base_url" \
        --clone-protocol https \
        --skip-workspace \
        --gcp-project "${GCP_PROJECT:?GCP_PROJECT must be set}" \
        --secret-id "${GITLAB_TOKEN_SECRET_ID:-gitlab-token}"
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
            [[ -d "$repo_path/.git" ]] || continue
            project_name=$(basename "$repo_path")

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

        FAILED=0
        for exit_file in "$WORK_TMPDIR"/*.exit; do
            [[ -f "$exit_file" ]] || continue
            code=$(cat "$exit_file")
            if [[ "$code" != "0" ]]; then
                log_json "WARNING" "env_drift failed for $(basename "$exit_file" .exit)"
                FAILED=$((FAILED + 1))
            fi
        done

        if [[ $FAILED -gt 0 ]]; then
            log_json "ERROR" "$FAILED repo(s) failed in env_drift"
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
            "$@"
        ;;

    file_drift)
        WORKSPACE_ROOT="${REPO_ROOT:-/workspace/repos/fastossb}"
        SUBGROUP="${SUBGROUP:-ndl_core}"
        GITLAB_BASE_URL="${GITLAB_BASE_URL:-https://dot-portal.de.pri.o2.com/gitlab}"

        clone_repos "$WORKSPACE_ROOT" "$GITLAB_BASE_URL"

        exec python3 "$SCRIPTS_DIR/report_branch_discrepancies_by_content.py" \
            --root "$WORKSPACE_ROOT/$SUBGROUP" \
            "$@"
        ;;

    *)
        log_json "ERROR" "Unknown report type: $REPORT_TYPE. Valid types: orphan_datasets, env_drift, commit_drift, file_drift"
        exit 1
        ;;
esac
