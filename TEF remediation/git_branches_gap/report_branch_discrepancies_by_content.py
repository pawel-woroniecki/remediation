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
GCS_PREFIX_DEFAULT = "branch-drift/content"

DISCREPANCY_DEFS: list[dict[str, str]] = [
    {"name": "prod_not_in_master", "left": "origin/master",     "right": "origin/production"},
    {"name": "prod_not_in_test",   "left": "origin/test",       "right": "origin/production"},
    {"name": "test_not_in_master", "left": "origin/master",     "right": "origin/test"},
    {"name": "test_not_in_prod",   "left": "origin/production", "right": "origin/test"},
    {"name": "master_not_in_test", "left": "origin/test",       "right": "origin/master"},
    {"name": "master_not_in_prod", "left": "origin/production", "right": "origin/master"},
]

# Maps raw git diff --name-status codes to human-readable difference types.
CHANGE_TYPE_MAP: dict[str, str] = {
    "A": "right_only",
    "D": "deleted_in_right",
    "M": "different_content",
    "R": "renamed_in_right",
    "C": "copied_in_right",
    "T": "different_content",
    "U": "different_content",
    "X": "different_content",
}


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


def get_merge_base(repo_path: str, left: str, right: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", repo_path, "merge-base", left, right],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip().splitlines()[0].strip()


def get_content_diff(
    repo_path: str,
    left: str,
    right: str,
    compare_mode: str,
) -> tuple[list[dict[str, str]], bool]:
    """
    Returns (diff_rows, success).

    diff_rows: list of {file_path, raw_change_type, difference_type}

    merge_base mode: diffs from the common ancestor to right branch tip,
    matching GitLab compare semantics.
    direct mode: diffs the two branch tips directly.
    """
    if compare_mode == "merge_base":
        base = get_merge_base(repo_path, left, right)
        if not base:
            return [], False
        result = subprocess.run(
            ["git", "-C", repo_path, "diff", "--name-status", base, right],
            capture_output=True,
            text=True,
        )
    else:
        result = subprocess.run(
            ["git", "-C", repo_path, "diff", "--name-status", left, right],
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        return [], False

    rows: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        raw_status = parts[0].strip()
        # Strip numeric suffix (similarity score) from R/C codes, e.g. R100 → R
        status_code = raw_status.rstrip("0123456789")
        file_path = parts[-1].strip()
        if not file_path:
            continue
        difference_type = CHANGE_TYPE_MAP.get(status_code)
        if not difference_type:
            continue
        rows.append({
            "file_path": file_path,
            "raw_change_type": raw_status,
            "difference_type": difference_type,
        })

    return rows, True


def get_file_metadata(
    repo_path: str,
    branch: str,
    file_path: str,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Fetches creation commit and last-change commit for file_path on branch.
    Results are cached to avoid redundant git calls when the same file
    appears in multiple discrepancy directions.
    """
    cache_key = f"{repo_path}|{branch}|{file_path}"
    if cache_key in cache:
        return cache[cache_key]

    exists_result = subprocess.run(
        ["git", "-C", repo_path, "ls-tree", "-r", "--name-only", branch, "--", file_path],
        capture_output=True,
        text=True,
    )
    exists = exists_result.returncode == 0 and bool(exists_result.stdout.strip())

    empty: dict[str, Any] = {
        "exists_on_right_branch": False,
        "created_commit": "", "created_at": "", "created_author": "",
        "created_author_email": "", "created_message": "",
        "last_change_commit": "", "last_change_at": "", "last_change_author": "",
        "last_change_author_email": "", "last_change_message": "",
    }

    if not exists:
        cache[cache_key] = empty
        return empty

    def _log(extra: list[str]) -> dict[str, str]:
        r = subprocess.run(
            ["git", "-C", repo_path, "log"] + extra + [
                "--format=%H|%aI|%an|%ae|%s", branch, "--", file_path,
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return {"commit": "", "date": "", "author": "", "email": "", "message": ""}
        parts = r.stdout.strip().splitlines()[0].split("|", 4)
        return {
            "commit":  parts[0] if len(parts) > 0 else "",
            "date":    parts[1] if len(parts) > 1 else "",
            "author":  parts[2] if len(parts) > 2 else "",
            "email":   parts[3] if len(parts) > 3 else "",
            "message": parts[4] if len(parts) > 4 else "",
        }

    created = _log(["--diff-filter=A", "--follow", "-n", "1"])
    last    = _log(["-n", "1"])

    result: dict[str, Any] = {
        "exists_on_right_branch":   True,
        "created_commit":           created["commit"],
        "created_at":               created["date"],
        "created_author":           created["author"],
        "created_author_email":     created["email"],
        "created_message":          created["message"],
        "last_change_commit":       last["commit"],
        "last_change_at":           last["date"],
        "last_change_author":       last["author"],
        "last_change_author_email": last["email"],
        "last_change_message":      last["message"],
    }
    cache[cache_key] = result
    return result


def content_severity(unique_files: int) -> str:
    if unique_files == 0:
        return "none"
    if unique_files <= 10:
        return "low"
    if unique_files <= 50:
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
        description="File-content-based branch drift report across master / test / production."
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
    parser.add_argument(
        "--compare-mode",
        choices=["merge_base", "direct"],
        default="merge_base",
        help=(
            "merge_base: diff from common ancestor to right branch tip, matching "
            "GitLab compare semantics (default). "
            "direct: diff the two branch tips directly."
        ),
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
        log_step(f"Compare mode: {args.compare_mode}")

        output_root = Path(args.output_dir).resolve()
        run_dir = output_root / f"file_drift_{args.date_tag}_{args.compare_mode}"
        run_dir.mkdir(parents=True, exist_ok=True)
        log_step(f"Output directory: {run_dir}")

        file_count_rows: list[dict[str, Any]] = []
        all_detail_rows: list[dict[str, Any]] = []
        kpi_rows: list[dict[str, Any]] = []

        # Shared metadata cache across all repos and directions to avoid
        # redundant git log calls for files that appear in multiple directions.
        metadata_cache: dict[str, dict[str, Any]] = {}

        problem_statement_template = (
            "File differs between merge-base({left}, {right}) and {right}, "
            "matching GitLab compare semantics."
            if args.compare_mode == "merge_base"
            else "File differs between branch tips {left} and {right}."
        )

        for repo_path in repos:
            repo = repo_path.name
            log_step(f"Repo: {repo}")
            path_str = str(repo_path)

            has_master = has_remote_branch(path_str, "master")
            has_test   = has_remote_branch(path_str, "test")
            has_prod   = has_remote_branch(path_str, "production")

            branch_present = {
                "master":     has_master,
                "test":       has_test,
                "production": has_prod,
            }

            dir_results: dict[str, dict[str, Any]] = {}

            for d in DISCREPANCY_DEFS:
                left, right = d["left"], d["right"]
                left_b  = left.split("/", 1)[1]
                right_b = right.split("/", 1)[1]

                if not (branch_present.get(left_b) and branch_present.get(right_b)):
                    dir_results[d["name"]] = {
                        "status": "missing_branch",
                        "unique_files": None,
                        "right_only": None,
                        "deleted_in_right": None,
                        "renamed_in_right": None,
                        "copied_in_right": None,
                        "different_content": None,
                    }
                    kpi_rows.append({
                        "execution_id": execution_id,
                        "repo": repo,
                        "left_branch": left,
                        "right_branch": right,
                        "drift_type": "content",
                        "comparison_mode": args.compare_mode,
                        "unique_commits": None,
                        "unique_files": None,
                        "severity": "N/A",
                        "status": "missing_branch",
                    })
                    continue

                diff_rows, ok = get_content_diff(path_str, left, right, args.compare_mode)

                if not ok:
                    dir_results[d["name"]] = {
                        "status": "error",
                        "unique_files": None,
                        "right_only": None,
                        "deleted_in_right": None,
                        "renamed_in_right": None,
                        "copied_in_right": None,
                        "different_content": None,
                    }
                    kpi_rows.append({
                        "execution_id": execution_id,
                        "repo": repo,
                        "left_branch": left,
                        "right_branch": right,
                        "drift_type": "content",
                        "comparison_mode": args.compare_mode,
                        "unique_commits": None,
                        "unique_files": None,
                        "severity": "N/A",
                        "status": "error",
                    })
                    continue

                unique_files = len({r["file_path"] for r in diff_rows})
                counts = {dt: 0 for dt in ("right_only", "deleted_in_right", "renamed_in_right", "copied_in_right", "different_content")}
                for row in diff_rows:
                    dt = row["difference_type"]
                    if dt in counts:
                        counts[dt] += 1

                problem = problem_statement_template.format(left=left, right=right)

                for row in diff_rows:
                    meta = get_file_metadata(path_str, right, row["file_path"], metadata_cache)
                    all_detail_rows.append({
                        "repo": repo,
                        "discrepancy": d["name"],
                        "left_branch": left,
                        "right_branch": right,
                        "compare_mode": args.compare_mode,
                        "file_path": row["file_path"],
                        "raw_change_type": row["raw_change_type"],
                        "difference_type": row["difference_type"],
                        "exists_on_right_branch": meta["exists_on_right_branch"],
                        "created_commit": meta["created_commit"],
                        "created_at": meta["created_at"],
                        "created_author": meta["created_author"],
                        "created_author_email": meta["created_author_email"],
                        "created_message": meta["created_message"],
                        "last_change_commit": meta["last_change_commit"],
                        "last_change_at": meta["last_change_at"],
                        "last_change_author": meta["last_change_author"],
                        "last_change_author_email": meta["last_change_author_email"],
                        "last_change_message": meta["last_change_message"],
                        "problem_statement": problem,
                    })

                dir_results[d["name"]] = {
                    "status": "ok",
                    "unique_files": unique_files,
                    **counts,
                }
                kpi_rows.append({
                    "execution_id": execution_id,
                    "repo": repo,
                    "left_branch": left,
                    "right_branch": right,
                    "drift_type": "content",
                    "comparison_mode": args.compare_mode,
                    "unique_commits": None,
                    "unique_files": unique_files,
                    "severity": content_severity(unique_files),
                    "status": "ok",
                })

            def _val(dir_name: str, field: str) -> str:
                r = dir_results.get(dir_name, {})
                if not r or r.get("status") in ("missing_branch", "error"):
                    return "N/A"
                v = r.get(field)
                return "N/A" if v is None else str(v)

            file_count_rows.append({
                "repo": repo,
                "has_master": has_master,
                "has_test": has_test,
                "has_production": has_prod,
                "master_files_not_in_test_by_content":   _val("master_not_in_test", "unique_files"),
                "test_files_not_in_master_by_content":   _val("test_not_in_master", "unique_files"),
                "prod_files_not_in_test_by_content":     _val("prod_not_in_test",   "unique_files"),
                "test_files_not_in_prod_by_content":     _val("test_not_in_prod",   "unique_files"),
                "prod_files_not_in_master_by_content":   _val("prod_not_in_master", "unique_files"),
                "master_files_not_in_prod_by_content":   _val("master_not_in_prod", "unique_files"),
            })

        # Write CSVs
        log_step("Writing CSV files ...")
        write_csv(
            run_dir / f"file_counts_{args.date_tag}.csv",
            sorted(file_count_rows, key=lambda r: r["repo"]),
        )
        write_csv(
            run_dir / f"details_{args.date_tag}.csv",
            sorted(all_detail_rows, key=lambda r: (r["repo"], r["discrepancy"], r["file_path"])),
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
                    "drift_type": "content",
                    "discrepancy": r["discrepancy"],
                    "commit_sha": r["last_change_commit"] or None,
                    "commit_date": r["last_change_at"] or None,
                    "author": r["last_change_author"] or None,
                    "file_path": r["file_path"],
                    "change_type": r["raw_change_type"],
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
                "report_type": "file_drift",
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
                        "report_type": "file_drift",
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
