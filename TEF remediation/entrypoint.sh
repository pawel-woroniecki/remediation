#!/bin/bash
set -euo pipefail

# JSON logging helper — outputs Cloud Logging-compatible JSON to stdout.
log_json() {
  local severity="$1"
  local message="$2"
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

        log_json "INFO" "Phase 2: running env_drift for each repo in $SUBGROUP_ROOT"
        FAILED=0
        for repo_path in "$SUBGROUP_ROOT"/*/; do
            [[ -d "$repo_path/.git" ]] || continue
            project_name=$(basename "$repo_path")
            # Fresh EXECUTION_ID per repo so each product gets its own audit row.
            EXECUTION_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
            export EXECUTION_ID
            log_json "INFO" "env_drift: $project_name (execution_id=$EXECUTION_ID)"
            python3 "$SCRIPTS_DIR/generate_code_environment_drift_report.py" \
                --project-name "$project_name" \
                --repo-path "$repo_path" \
                "$@" || {
                log_json "WARNING" "env_drift failed for $project_name"
                FAILED=$((FAILED + 1))
            }
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
