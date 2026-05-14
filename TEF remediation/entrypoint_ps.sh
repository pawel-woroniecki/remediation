#!/bin/bash
# DEPRECATED — commit_drift and file_drift are now handled by entrypoint.sh
# using Python scripts in Dockerfile.python. This file is no longer used.
set -euo pipefail

REPORT_TYPE="${1:-}"
if [[ -z "$REPORT_TYPE" ]]; then
    echo "Usage: run-report <report_type> [args...]"
    echo "Valid report types: commit_drift, file_drift"
    exit 1
fi
shift

SCRIPTS_DIR="/app/scripts"

case "$REPORT_TYPE" in

    commit_drift)
        exec pwsh "$SCRIPTS_DIR/report_branch_discrepancies_by_commit.ps1" "$@"
        ;;

    file_drift)
        exec pwsh "$SCRIPTS_DIR/report_branch_discrepancies_by_content.ps1" "$@"
        ;;

    *)
        echo "Unknown report type: '$REPORT_TYPE'"
        echo "Valid types: commit_drift, file_drift"
        exit 1
        ;;
esac
