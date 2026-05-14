#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from google.cloud import bigquery, storage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GCS_BUCKET_DEFAULT = "to-be-added-later"
GCS_PREFIX_DEFAULT = "branch-drift/commit"

DISCREPANCY_DEFS: list[dict[str, str]] = [
    {
        "name": "prod_not_in_master",
        "left": "origin/master",
        "right": "origin/production",
        "problem": "Commits in production not present in master (cherry-pick, no merges).",
    },
    {
        "name": "prod_not_in_test",
        "left": "origin/test",
        "right": "origin/production",
        "problem": "Commits in production not present in test (cherry-pick, no merges).",
    },
    {
        "name": "test_not_in_master",
        "left": "origin/master",
        "right": "origin/test",
        "problem": "Commits in test not present in master (cherry-pick, no merges).",
    },
    {
        "name": "test_not_in_prod",
        "left": "origin/production",
        "right": "origin/test",
        "problem": "Commits in test not present in production (cherry-pick, no merges).",
    },
    {
        "name": "master_not_in_test",
        "left": "origin/test",
        "right": "origin/master",
        "problem": "Commits in master not present in test (cherry-pick, no merges).",
    },
    {
        "name": "master_not_in_prod",
        "left": "origin/production",
        "right": "origin/master",
        "problem": "Commits in master not present in production (cherry-pick, no merges).",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def default_output_dir() -> str:
    if os.environ.get("OUTPUT_DIR"):
        return os.environ["OUTPUT_DIR"]
    path = Path(__file__).resolve()
    return str(path.parents[2] / "outputs") if len(path.parents) > 2 else str(path.parent / "outputs")


def log_step(message: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def has_remote_branch(repo_path: str, branch: str) -> bool:
    result = subprocess.run(
        ["git", "-C", repo_path, "show-ref", "--verify", "--quiet",
         f"refs/remotes/origin/{branch}"],
        capture_output=True,
    )
    return result.returncode == 0


def get_detail_rows(
    repo_path: str,
    repo_name: str,
    left: str,
    right: str,
    discrepancy_name: str,
    problem_statement: str,
) -> tuple[list[dict[str, Any]], int, int]:
    """
    Returns (detail_rows, unique_file_count, unique_commit_count).

    Parses git log output that interleaves '@@@<meta>' commit header lines
    with file-path lines. Uses %aI for strict ISO 8601 author date with
    timezone so BigQuery TIMESTAMP parsing works without conversion.
    """
    result = subprocess.run(
        [
            "git", "-C", repo_path, "log",
            "--no-merges", "--right-only", "--cherry-pick",
            "--name-only", "--pretty=format:@@@%H|%aI|%an|%ae|%s",
            f"{left}...{right}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return [], 0, 0

    rows: list[dict[str, Any]] = []
    current_hash = current_date = current_author = current_email = current_msg = ""
    file_set: set[str] = set()
    commit_set: set[str] = set()

    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        if line.startswith("@@@"):
            parts = line[3:].split("|", 4)
            if len(parts) == 5:
                current_hash, current_date, current_author, current_email, current_msg = parts
                commit_set.add(current_hash)
            continue
        if not current_hash:
            continue
        file_path = line.strip()
        if not file_path:
            continue
        file_set.add(file_path)
        rows.append({
            "repo": repo_name,
            "discrepancy": discrepancy_name,
            "left_branch": left,
            "right_branch": right,
            "commit": current_hash,
            "created_at": current_date,
            "author": current_author,
            "author_email": current_email,
            "message": current_msg,
            "file_path": file_path,
            "problem_statement": problem_statement,
        })

    return rows, len(file_set), len(commit_set)


def commit_severity(unique_commits: int) -> str:
    if unique_commits == 0:
        return "none"
    if unique_commits <= 5:
        return "low"
    if unique_commits <= 20:
        return "medium"
    return "high"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_to_bigquery(
    client: bigquery.Client,
    table_id: str,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    errors = client.insert_rows_json(table_id, rows)
    if errors:
        raise RuntimeError(f"BigQuery streaming insert errors for {table_id}: {errors}")


def upload_to_gcs(
    bucket_name: str,
    gcs_prefix: str,
    execution_id: str,
    local_dir: Path,
) -> None:
    if bucket_name == GCS_BUCKET_DEFAULT:
        log_step("GCS upload skipped: --gcs-bucket not configured.")
        return
    try:
        gcs_client = storage.Client()
        bucket = gcs_client.bucket(bucket_name)
        for local_file in sorted(local_dir.iterdir()):
            if not local_file.is_file():
                continue
            blob_name = f"{gcs_prefix}/{execution_id}/{local_dir.name}/{local_file.name}"
            bucket.blob(blob_name).upload_from_filename(str(local_file))
            log_step(f"  Uploaded → gs://{bucket_name}/{blob_name}")
    except Exception as exc:
        log_step(f"WARNING: GCS upload failed: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Commit-based branch drift report across master / test / production."
    )
    parser.add_argument(
        "--root",
        required=True,
        help="Subgroup directory containing cloned repos, e.g. /workspace/repos/fastossb/ndl_core.",
    )
    parser.add_argument("--date-tag", default=date.today().strftime("%Y-%m-%d"))
    parser.add_argument("--output-dir", default=default_output_dir())
    parser.add_argument("--gcp-project", default=None)
    parser.add_argument(
        "--reporting-project",
        default=None,
        help="GCP project for devops_reports dataset; defaults to --gcp-project.",
    )
    parser.add_argument("--gcs-bucket", default=GCS_BUCKET_DEFAULT)
    parser.add_argument("--gcs-prefix", default=GCS_PREFIX_DEFAULT)
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    status = "success"
    bq_client: bigquery.Client | None = None

    execution_id = os.environ.get("EXECUTION_ID")
    if not execution_id:
        raise ValueError("EXECUTION_ID environment variable must be set")

    args = parse_args()
    reporting_project = args.reporting_project or args.gcp_project
    if not reporting_project:
        raise ValueError("--reporting-project or --gcp-project must be set")

    try:
        root = Path(args.root).resolve()
        if not root.exists():
            raise ValueError(f"Root path not found: {root}")

        bq_client = bigquery.Client(project=reporting_project)

        repos = sorted(p for p in root.iterdir() if p.is_dir() and (p / ".git").exists())
        log_step(f"Found {len(repos)} git repos under {root}")

        output_root = Path(args.output_dir).resolve()
        run_dir = output_root / f"commit_drift_{args.date_tag}"
        run_dir.mkdir(parents=True, exist_ok=True)
        log_step(f"Output directory: {run_dir}")

        commit_count_rows: list[dict[str, Any]] = []
        file_count_rows: list[dict[str, Any]] = []
        all_detail_rows: list[dict[str, Any]] = []
        kpi_rows: list[dict[str, Any]] = []

        for repo_path in repos:
            repo = repo_path.name
            log_step(f"Repo: {repo}")
            path_str = str(repo_path)

            has_master = has_remote_branch(path_str, "master")
            has_test = has_remote_branch(path_str, "test")
            has_prod = has_remote_branch(path_str, "production")

            branch_present = {
                "master": has_master,
                "test": has_test,
                "production": has_prod,
            }

            # Per-direction results used to build the summary matrix CSVs.
            dir_results: dict[str, dict[str, Any]] = {}

            for d in DISCREPANCY_DEFS:
                left, right = d["left"], d["right"]
                left_b = left.split("/", 1)[1]   # strip "origin/"
                right_b = right.split("/", 1)[1]

                if not (branch_present.get(left_b) and branch_present.get(right_b)):
                    dir_results[d["name"]] = {
                        "status": "missing_branch",
                        "unique_commits": None,
                        "unique_files": None,
                    }
                    kpi_rows.append({
                        "execution_id": execution_id,
                        "repo": repo,
                        "left_branch": left,
                        "right_branch": right,
                        "drift_type": "commit",
                        "comparison_mode": "cherry_pick_no_merges",
                        "unique_commits": None,
                        "unique_files": None,
                        "severity": "N/A",
                        "status": "missing_branch",
                    })
                    continue

                rows_for_dir, unique_files, unique_commits = get_detail_rows(
                    path_str, repo, left, right, d["name"], d["problem"]
                )
                all_detail_rows.extend(rows_for_dir)
                dir_results[d["name"]] = {
                    "status": "ok",
                    "unique_commits": unique_commits,
                    "unique_files": unique_files,
                }
                kpi_rows.append({
                    "execution_id": execution_id,
                    "repo": repo,
                    "left_branch": left,
                    "right_branch": right,
                    "drift_type": "commit",
                    "comparison_mode": "cherry_pick_no_merges",
                    "unique_commits": unique_commits,
                    "unique_files": unique_files,
                    "severity": commit_severity(unique_commits),
                    "status": "ok",
                })

            def _val(dir_name: str, field: str) -> str:
                r = dir_results.get(dir_name, {})
                if not r or r.get("status") == "missing_branch":
                    return "N/A"
                v = r.get(field)
                return "N/A" if v is None else str(v)

            commit_count_rows.append({
                "repo": repo,
                "has_master": has_master,
                "has_test": has_test,
                "has_production": has_prod,
                "master_not_in_test_commits_no_merges": _val("master_not_in_test", "unique_commits"),
                "test_not_in_master_commits_no_merges": _val("test_not_in_master", "unique_commits"),
                "prod_not_in_test_commits_no_merges": _val("prod_not_in_test", "unique_commits"),
                "test_not_in_prod_commits_no_merges": _val("test_not_in_prod", "unique_commits"),
                "prod_not_in_master_commits_no_merges": _val("prod_not_in_master", "unique_commits"),
                "master_not_in_prod_commits_no_merges": _val("master_not_in_prod", "unique_commits"),
            })
            file_count_rows.append({
                "repo": repo,
                "has_master": has_master,
                "has_test": has_test,
                "has_production": has_prod,
                "master_files_not_in_test_no_merges": _val("master_not_in_test", "unique_files"),
                "test_files_not_in_master_no_merges": _val("test_not_in_master", "unique_files"),
                "prod_files_not_in_test_no_merges": _val("prod_not_in_test", "unique_files"),
                "test_files_not_in_prod_no_merges": _val("test_not_in_prod", "unique_files"),
                "prod_files_not_in_master_no_merges": _val("prod_not_in_master", "unique_files"),
                "master_files_not_in_prod_no_merges": _val("master_not_in_prod", "unique_files"),
            })

        # Write CSVs
        log_step("Writing CSV files ...")
        write_csv(
            run_dir / f"commit_counts_{args.date_tag}.csv",
            sorted(commit_count_rows, key=lambda r: r["repo"]),
        )
        write_csv(
            run_dir / f"file_counts_{args.date_tag}.csv",
            sorted(file_count_rows, key=lambda r: r["repo"]),
        )
        write_csv(
            run_dir / f"details_{args.date_tag}.csv",
            sorted(
                all_detail_rows,
                key=lambda r: (r["repo"], r["discrepancy"], r["created_at"], r["commit"], r["file_path"]),
            ),
        )
        write_csv(
            run_dir / f"totals_{args.date_tag}.csv",
            sorted(kpi_rows, key=lambda r: (r["repo"], r["left_branch"], r["right_branch"])),
        )

        # Upload CSVs to GCS
        upload_to_gcs(args.gcs_bucket, args.gcs_prefix, execution_id, run_dir)

        # BigQuery: evidence → kpis → execution record
        log_step("Writing to BigQuery ...")
        write_to_bigquery(
            bq_client,
            f"{reporting_project}.devops_reports.branch_drift_evidence",
            [
                {
                    "execution_id": execution_id,
                    "repo": r["repo"],
                    "drift_type": "commit",
                    "discrepancy": r["discrepancy"],
                    "commit_sha": r["commit"],
                    "commit_date": r["created_at"] or None,
                    "author": r["author"],
                    "file_path": r["file_path"],
                    "change_type": None,
                    "problem_statement": r["problem_statement"],
                }
                for r in all_detail_rows
            ],
        )
        write_to_bigquery(
            bq_client,
            f"{reporting_project}.devops_reports.branch_drift_kpis",
            kpi_rows,
        )
        write_to_bigquery(
            bq_client,
            f"{reporting_project}.devops_reports.executions",
            [{
                "execution_id": execution_id,
                "report_type": "commit_drift",
                "execution_ts": datetime.now(timezone.utc).isoformat(),
                "environment": "prod",
                "git_ref": None,
                "source_mode": "branch",
                "triggered_by": "ui",
                "status": status,
            }],
        )

        log_step("Done.")
        print(f"Report written to: {run_dir}")
        return 0

    except Exception:
        status = "failed"
        if bq_client is not None:
            try:
                write_to_bigquery(
                    bq_client,
                    f"{reporting_project}.devops_reports.executions",
                    [{
                        "execution_id": execution_id,
                        "report_type": "commit_drift",
                        "execution_ts": datetime.now(timezone.utc).isoformat(),
                        "environment": "prod",
                        "git_ref": None,
                        "source_mode": "branch",
                        "triggered_by": "ui",
                        "status": "failed",
                    }],
                )
            except Exception:
                pass
        raise


if __name__ == "__main__":
    sys.exit(main())
