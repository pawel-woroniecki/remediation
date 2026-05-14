from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import google.auth
import google.auth.transport.requests
from google.cloud import bigquery, storage


GCS_BUCKET_DEFAULT = "to-be-added-later"


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


def default_output_dir() -> str:
    if os.environ.get("OUTPUT_DIR"):
        return os.environ["OUTPUT_DIR"]
    path = Path(__file__).resolve()
    # parents[2] is the project root when the script is nested two directories deep.
    # Fall back to a sibling outputs/ folder when running flat (e.g. inside Docker).
    return str(path.parents[2] / "outputs") if len(path.parents) > 2 else str(path.parent / "outputs")


def log_step(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def run_command(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed.stdout


def resolve_branch_ref(repo_path: Path, branch_name: str) -> str | None:
    # Check remote first so the report can read the canonical branch even when
    # the local branch does not exist or is stale.
    for ref in (f"origin/{branch_name}", branch_name):
        completed = subprocess.run(
            ["git", "-C", str(repo_path), "show-ref", "--verify", "--quiet", f"refs/remotes/{ref}" if ref.startswith("origin/") else f"refs/heads/{ref}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            return ref
    return None


def read_file_from_git_ref(repo_path: Path, git_ref: str, relative_path: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(repo_path), "show", f"{git_ref}:{relative_path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def gcp_access_token() -> str:
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials.token


def api_get(token: str, url: str) -> dict[str, Any]:
    request = Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}\n{body}") from exc


def api_post_json(token: str, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}\n{body}") from exc


# Fix 4 & 5: check jobComplete and paginate through all result pages.
def bigquery_query(token: str, project_id: str, sql: str, timeout_ms: int = 30000) -> list[dict[str, Any]]:
    response = api_post_json(
        token,
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{quote(project_id)}/queries",
        {"query": sql, "useLegacySql": False, "timeoutMs": timeout_ms},
    )
    if not response.get("jobComplete"):
        job_id = response.get("jobReference", {}).get("jobId", "unknown")
        raise RuntimeError(f"BigQuery query did not complete within {timeout_ms}ms (jobId={job_id})")

    fields = response.get("schema", {}).get("fields", [])
    parsed: list[dict[str, Any]] = []

    def _parse_rows(rows: list[Any]) -> None:
        for row in rows:
            values = row.get("f", [])
            item: dict[str, Any] = {}
            for field, value in zip(fields, values):
                item[field["name"]] = value.get("v")
            parsed.append(item)

    _parse_rows(response.get("rows", []))

    page_token = response.get("pageToken")
    job_id = response.get("jobReference", {}).get("jobId")
    while page_token and job_id:
        url = (
            f"https://bigquery.googleapis.com/bigquery/v2/projects/{quote(project_id)}"
            f"/queries/{quote(job_id)}?pageToken={quote(page_token)}"
        )
        page_response = api_get(token, url)
        _parse_rows(page_response.get("rows", []))
        page_token = page_response.get("pageToken")

    return parsed


def list_datasets(token: str, project_id: str) -> list[str]:
    datasets: list[str] = []
    page_token: str | None = None
    while True:
        url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{quote(project_id)}/datasets?all=true"
        if page_token:
            url += f"&pageToken={quote(page_token)}"
        response = api_get(token, url)
        for item in response.get("datasets", []):
            dataset_id = item.get("datasetReference", {}).get("datasetId")
            if dataset_id:
                datasets.append(dataset_id)
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return sorted(set(datasets))


def extract_yaml_like_block(text: str, block_name: str, indent: int = 0) -> str:
    pattern = re.compile(
        rf"(?ms)^{' ' * indent}{re.escape(block_name)}:\s*\n(?P<body>(?:^(?:{' ' * (indent + 2)}).*\n?)*)"
    )
    match = pattern.search(text)
    return match.group("body") if match else ""


def parse_simple_variables(block_text: str, indent: int) -> dict[str, str]:
    variables: dict[str, str] = {}
    for raw_line in block_text.splitlines():
        if not raw_line.startswith(" " * indent):
            continue
        stripped = raw_line[indent:]
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        variables[key.strip()] = value.strip().strip('"').strip("'")
    return variables


def load_gitlab_variables_from_text(text: str) -> dict[str, str]:
    # Merge top-level variables with deploy job overrides because some repos
    # declare BQ_DATASET_NAMES globally while others keep prod values per job.
    top_variables = parse_simple_variables(extract_yaml_like_block(text, "variables", indent=0), indent=2)
    merged = dict(top_variables)
    for job_name in ("deploy_to_prod_bq", "deploy_to_prod_dbt", "deploy_to_prod_python"):
        prod_job = extract_yaml_like_block(text, job_name, indent=0)
        if not prod_job:
            continue
        job_variables = parse_simple_variables(extract_yaml_like_block(prod_job, "variables", indent=2), indent=4)
        merged.update(job_variables)
    return merged


def parse_dataset_names(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


@dataclass
class RepoDatasetReference:
    repo: str
    ci_path: str
    git_ref: str | None
    datasets: list[str]


def collect_repo_dataset_references(subgroup_root: Path, branch_name: str) -> tuple[list[RepoDatasetReference], dict[str, list[str]]]:
    repos = sorted(path for path in subgroup_root.iterdir() if path.is_dir() and (path / ".git").exists())
    references: list[RepoDatasetReference] = []
    dataset_to_repos: dict[str, list[str]] = defaultdict(list)
    repo_total = len(repos)

    log_step(f"Scanning subgroup repos in {subgroup_root} ... found {repo_total} git repos.")

    for index, repo in enumerate(repos, start=1):
        log_step(f"Repo {index}/{repo_total}: {repo.name}")
        git_ref = resolve_branch_ref(repo, branch_name)
        if not git_ref:
            log_step(f"  Skipping {repo.name}: branch/ref '{branch_name}' was not found locally or on origin.")
            continue
        try:
            # Read .gitlab-ci.yml directly from the selected ref so the report
            # reflects deployed branch content rather than the current worktree.
            ci_text = read_file_from_git_ref(repo, git_ref, ".gitlab-ci.yml")
            if ci_text is None:
                log_step(f"  Skipping {repo.name}: .gitlab-ci.yml not found at {git_ref}.")
                continue
            variables = load_gitlab_variables_from_text(ci_text)
        except Exception:
            log_step(f"  Skipping {repo.name}: failed to read or parse .gitlab-ci.yml at {git_ref}.")
            continue
        datasets = parse_dataset_names(variables.get("BQ_DATASET_NAMES"))
        log_step(f"  Using {git_ref}; datasets declared: {len(datasets)}")
        references.append(
            RepoDatasetReference(
                repo=repo.name,
                ci_path=str((repo / ".gitlab-ci.yml").relative_to(subgroup_root.parent)).replace("\\", "/"),
                git_ref=git_ref,
                datasets=datasets,
            )
        )
        for dataset in datasets:
            if repo.name not in dataset_to_repos[dataset]:
                dataset_to_repos[dataset].append(repo.name)

    for repos_for_dataset in dataset_to_repos.values():
        repos_for_dataset.sort()
    log_step(
        f"Finished repo scan: repos with BQ_DATASET_NAMES={len([ref for ref in references if ref.datasets])}; "
        f"distinct referenced datasets={len(dataset_to_repos)}."
    )
    return references, dataset_to_repos


def fetch_dataset_objects(token: str, project_id: str, dataset: str) -> tuple[list[dict[str, str]], str | None]:
    objects: list[dict[str, str]] = []
    errors: list[str] = []
    try:
        # Tables/views and routines can fail independently on some datasets, so
        # capture partial results instead of aborting the whole report.
        table_rows = bigquery_query(
            token,
            project_id,
            f"""
            SELECT table_name, table_type
            FROM `{project_id}`.{dataset}.INFORMATION_SCHEMA.TABLES
            ORDER BY table_name
            """.strip(),
        )
    except RuntimeError as exc:
        errors.append(f"tables: {exc}")
        table_rows = []
    for row in table_rows:
        objects.append(
            {
                "dataset": dataset,
                "object_name": str(row.get("table_name", "")),
                "object_type": str(row.get("table_type", "unknown")).lower().replace(" ", "_"),
            }
        )

    try:
        routine_rows = bigquery_query(
            token,
            project_id,
            f"""
            SELECT routine_name, routine_type
            FROM `{project_id}`.{dataset}.INFORMATION_SCHEMA.ROUTINES
            ORDER BY routine_name
            """.strip(),
        )
    except RuntimeError as exc:
        errors.append(f"routines: {exc}")
        routine_rows = []
    for row in routine_rows:
        objects.append(
            {
                "dataset": dataset,
                "object_name": str(row.get("routine_name", "")),
                "object_type": str(row.get("routine_type", "routine")).lower().replace(" ", "_"),
            }
        )

    return objects, "; ".join(errors) if errors else None


def summarize_object_types(objects: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in objects:
        counts[item["object_type"]] += 1
    return dict(sorted(counts.items()))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def write_to_bigquery(
    client: bigquery.Client,
    table_id: str,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    errors = client.insert_rows_json(table_id, rows)
    if errors:
        raise RuntimeError(f"BigQuery insert errors: {errors}")


def write_markdown(path: Path, summary: dict[str, Any], unmatched_datasets: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("# Unmatched BigQuery Datasets Report")
    lines.append("")
    lines.append(f"- Generated UTC: {summary['generated_utc']}")
    lines.append(f"- BigQuery project: {summary['project_id']}")
    lines.append(f"- Subgroup: {summary['subgroup']}")
    lines.append(f"- Subgroup path: `{summary['subgroup_root']}`")
    lines.append(f"- Git ref used for repo-side matching: `{summary['git_ref']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Datasets scanned in BigQuery: {summary['datasets_scanned']}")
    lines.append(f"- Repos scanned in subgroup: {summary['repos_scanned']}")
    lines.append(f"- Repos with `BQ_DATASET_NAMES`: {summary['repos_with_dataset_refs']}")
    lines.append(f"- Datasets referenced in GitLab CI: {summary['datasets_referenced']}")
    lines.append(f"- Unmatched datasets in BigQuery: {summary['unmatched_datasets']}")
    lines.append(f"- Datasets with metadata errors: {summary['datasets_with_errors']}")
    lines.append("")
    lines.append("## Unmatched Datasets")
    lines.append("")
    if not unmatched_datasets:
        lines.append("No unmatched datasets.")
        lines.append("")
    else:
        lines.append("| Dataset | Objects | Type Breakdown | Notes |")
        lines.append("| --- | ---: | --- | --- |")
        for item in unmatched_datasets:
            breakdown = ", ".join(f"{key}={value}" for key, value in item["object_type_counts"].items()) or "none"
            notes = item.get("error") or ""
            lines.append(f"| {item['dataset']} | {item['object_count']} | {breakdown} | {notes} |")
        lines.append("")
        lines.append("Object-level detail is written to `unmatched_objects.csv` and `unmatched_datasets.json`.")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan BigQuery prod datasets and flag datasets not referenced by any local subgroup repo."
    )
    parser.add_argument("--project-id", default="tefde-gcp-fastoss-prod")
    parser.add_argument(
        "--workspace-root",
        required=True,
        help="Parent folder that contains subgroup directories such as C:\\repos\\fastossb\\ndl_core.",
    )
    parser.add_argument("--subgroup", default="ndl_core")
    parser.add_argument("--git-ref", default="production")
    parser.add_argument("--output-dir", default=default_output_dir())
    parser.add_argument("--dataset-include-regex", default=".*")
    parser.add_argument("--dataset-exclude-regex", default="^_")
    parser.add_argument("--reporting-project", default=None, help="GCP project where devops_reports dataset exists; defaults to --gcp-project if omitted")
    parser.add_argument("--gcp-project", default=None)
    parser.add_argument(
        "--gcs-bucket",
        default=GCS_BUCKET_DEFAULT,
        help="GCS bucket where report output files are uploaded.",
    )
    parser.add_argument(
        "--gcs-prefix",
        default="orphan-datasets",
        help="GCS key prefix for report uploads. Default: orphan-datasets",
    )
    return parser.parse_args()


def main() -> int:
    status = "success"
    bq_client = None
    execution_id = os.environ.get("EXECUTION_ID")
    if not execution_id:
        raise ValueError("EXECUTION_ID must be set")
    args = parse_args()
    # Fix 3: resolve reporting_project before the try block so it is always
    # available in the except handler regardless of where the failure occurs.
    reporting_project = args.reporting_project or args.gcp_project
    try:
        # Fix 1: try block is now correctly indented at 4 spaces.
        workspace_root = Path(args.workspace_root).resolve()
        subgroup_root = (workspace_root / args.subgroup).resolve()
        bq_client = bigquery.Client(project=reporting_project)
        if not subgroup_root.exists():
            raise ValueError(f"Subgroup path not found: {subgroup_root}")

        output_root = Path(args.output_dir).resolve()
        output_root.mkdir(parents=True, exist_ok=True)

        log_step("Starting BigQuery orphan datasets report.")
        log_step(f"BigQuery project: {args.project_id}")
        log_step(f"Workspace root: {workspace_root}")
        log_step(f"Subgroup path: {subgroup_root}")
        log_step(f"Git ref for repo-side matching: {args.git_ref}")
        log_step(f"Output root: {output_root}")

        include_regex = re.compile(args.dataset_include_regex)
        exclude_regex = re.compile(args.dataset_exclude_regex) if args.dataset_exclude_regex else None

        log_step("Requesting GCP access token via Application Default Credentials.")
        token = gcp_access_token()
        log_step("Access token acquired.")

        log_step(f"Listing datasets from BigQuery project {args.project_id} ...")
        all_datasets = [
            dataset
            for dataset in list_datasets(token, args.project_id)
            if include_regex.search(dataset) and not (exclude_regex and exclude_regex.search(dataset))
        ]
        log_step(f"Datasets after include/exclude filters: {len(all_datasets)}")

        repo_refs, dataset_to_repos = collect_repo_dataset_references(subgroup_root, args.git_ref)

        unmatched_datasets: list[dict[str, Any]] = []
        unmatched_objects_rows: list[dict[str, Any]] = []
        dataset_errors: list[dict[str, str]] = []
        unmatched_candidates = [dataset for dataset in all_datasets if dataset not in dataset_to_repos]

        log_step(
            f"Managed datasets referenced by repos: {len(dataset_to_repos)}; "
            f"unmatched datasets to inspect: {len(unmatched_candidates)}."
        )

        for index, dataset in enumerate(all_datasets, start=1):
            # A dataset is considered managed as soon as at least one repo declares
            # it in BQ_DATASET_NAMES at the selected Git ref.
            if dataset in dataset_to_repos:
                continue
            unmatched_index = len(unmatched_datasets) + 1
            log_step(f"Unmatched dataset {unmatched_index}/{len(unmatched_candidates)}: {dataset} (dataset {index}/{len(all_datasets)} overall)")
            objects, error = fetch_dataset_objects(token, args.project_id, dataset)
            for item in objects:
                unmatched_objects_rows.append(item)
            if error:
                log_step(f"  Metadata issues for {dataset}: {error}")
                dataset_errors.append({"dataset": dataset, "error": error})
            log_step(f"  Objects found in {dataset}: {len(objects)}")
            unmatched_datasets.append(
                {
                    "dataset": dataset,
                    "object_count": len(objects),
                    "object_type_counts": summarize_object_types(objects),
                    "error": error,
                }
            )

        unmatched_datasets.sort(key=lambda item: item["dataset"])
        unmatched_dataset_rows = [
            {
                "dataset": item["dataset"],
                "object_count": item["object_count"],
                # Keep the CSV flat while preserving the object-type breakdown.
                "object_type_counts": json.dumps(item["object_type_counts"], ensure_ascii=True, sort_keys=True),
                "error": item.get("error") or "",
            }
            for item in unmatched_datasets
        ]

        summary = {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "project_id": args.project_id,
            "subgroup": args.subgroup,
            "subgroup_root": str(subgroup_root),
            "git_ref": args.git_ref,
            "datasets_scanned": len(all_datasets),
            "repos_scanned": len([path for path in subgroup_root.iterdir() if path.is_dir() and (path / ".git").exists()]),
            "repos_with_dataset_refs": len([ref for ref in repo_refs if ref.datasets]),
            "datasets_referenced": len(dataset_to_repos),
            "unmatched_datasets": len(unmatched_datasets),
            "datasets_with_errors": len(dataset_errors),
        }

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = output_root / f"{args.subgroup}_unmatched_bq_datasets_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        log_step(f"Writing report files to {run_dir}")

        write_markdown(run_dir / "report.md", summary, unmatched_datasets)
        write_csv(run_dir / "unmatched_datasets.csv", unmatched_dataset_rows)
        write_csv(run_dir / "unmatched_objects.csv", unmatched_objects_rows)
        write_csv(run_dir / "dataset_errors.csv", dataset_errors)
        write_csv(
            run_dir / "repo_dataset_references.csv",
            [
                {
                    "repo": ref.repo,
                    "ci_path": ref.ci_path,
                    "git_ref": ref.git_ref,
                    "datasets": ", ".join(ref.datasets),
                    "dataset_count": len(ref.datasets),
                }
                for ref in repo_refs
            ],
        )
        write_json(
            run_dir / "unmatched_datasets.json",
            {
                "summary": summary,
                "unmatched_datasets": unmatched_datasets,
                "unmatched_objects": unmatched_objects_rows,
                "dataset_errors": dataset_errors,
                "repo_dataset_references": [
                    {
                        "repo": ref.repo,
                        "ci_path": ref.ci_path,
                        "git_ref": ref.git_ref,
                        "datasets": ref.datasets,
                    }
                    for ref in repo_refs
                ],
            },
        )

        # Upload local report files to GCS before writing to BigQuery so the
        # files are preserved even if a BQ insert fails.
        upload_to_gcs(args.gcs_bucket, args.gcs_prefix, execution_id, run_dir)

        # Write findings before the execution record so that a failure during
        # the findings insert is still captured as status=failed.
        # Objects first, then dataset-level summary, then execution record.
        write_to_bigquery(
            bq_client,
            f"{reporting_project}.devops_reports.orphan_dataset_objects",
            [
                {
                    "execution_id": execution_id,
                    "dataset_name": obj["dataset"],
                    "object_type": obj["object_type"],
                    "object_name": obj["object_name"],
                    "last_modified": None,
                    "row_count": None,
                    "storage_mb": None,
                }
                for obj in unmatched_objects_rows
            ],
        )
        write_to_bigquery(
            bq_client,
            f"{reporting_project}.devops_reports.orphan_datasets",
            [
                {
                    "execution_id": execution_id,
                    "dataset_name": item["dataset"],
                    "project_id": args.project_id,
                    "orphan_status": "orphan",
                    "source_reference_found": False,
                    "last_modified": None,
                    "table_count": item["object_count"],
                    "owner": None,
                    "risk_score": 2 if item["object_count"] > 0 else 1,
                }
                for item in unmatched_datasets
            ],
        )

        write_to_bigquery(
            bq_client,
            f"{reporting_project}.devops_reports.executions",
            [{
                "execution_id": execution_id,
                "report_type": "orphan_datasets",
                "execution_ts": datetime.now(timezone.utc).isoformat(),
                "environment": "prod",
                "git_ref": args.git_ref,
                "source_mode": "branch",
                "triggered_by": "ui",
                "status": status,
            }],
        )

        log_step("Report generation completed.")
        print(f"Report written to: {run_dir}")
        print(json.dumps(summary, indent=2))
        return 0

    except Exception:
        status = "failed"
        # Fix 2: guard against bq_client being None when the failure occurs
        # before the client is initialised (e.g. bad --reporting-project value).
        if bq_client is not None:
            write_to_bigquery(
                bq_client,
                f"{reporting_project}.devops_reports.executions",
                [{
                    "execution_id": execution_id,
                    "report_type": "orphan_datasets",
                    "execution_ts": datetime.now(timezone.utc).isoformat(),
                    "environment": "prod",
                    "git_ref": args.git_ref,
                    "source_mode": "branch",
                    "triggered_by": "ui",
                    "status": status,
                }],
            )
        raise


if __name__ == "__main__":
    sys.exit(main())
