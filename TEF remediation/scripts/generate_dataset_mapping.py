#!/usr/bin/env python3
"""
Read BQ_DATASET_NAMES from each repo's .gitlab-ci.yml and write a JSON mapping
{dataset_name: repo_name} to GCS.

Intended as a Cloud Run job (report type: dataset_mapping).  The repos must
already be cloned locally — entrypoint.sh calls clone_repos() before exec-ing
this script.

Usage:
    python generate_dataset_mapping.py \
        --gcs-output gs://my-bucket/dataset-mapping/dataset_repo_map.json \
        [--workspace-root /workspace/repos/fastossb] \
        [--subgroup ndl_core]
"""

import argparse
import json
import sys
from pathlib import Path

import yaml
from google.cloud import storage

GITLAB_CI_FILE = ".gitlab-ci.yml"


def log(severity: str, message: str, **fields) -> None:
    """Write a Cloud Logging-compatible JSON log line."""
    entry = {"severity": severity, "message": message}
    entry.update(fields)
    print(json.dumps(entry), flush=True)


def build_dataset_repo_map(workspace_root: Path, subgroup: str) -> dict[str, str]:
    subgroup_root = workspace_root / subgroup
    if not subgroup_root.exists():
        log("ERROR", f"Subgroup directory not found: {subgroup_root}")
        sys.exit(1)

    dataset_repo_map: dict[str, str] = {}
    repos_found = 0

    for ci_path in sorted(subgroup_root.rglob(GITLAB_CI_FILE)):
        repo_name = ci_path.parent.name
        try:
            ci = yaml.safe_load(ci_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            log("WARNING", f"Could not parse {ci_path}: {exc}", repo=repo_name)
            continue

        raw = ci.get("variables", {}).get("BQ_DATASET_NAMES", "")
        if not raw:
            continue

        datasets = [d.strip() for d in str(raw).split(",") if d.strip()]
        repos_found += 1
        log("INFO", f"[{repo_name}] {len(datasets)} dataset(s)", repo=repo_name,
            datasets=datasets)

        for ds in datasets:
            if ds in dataset_repo_map:
                log("WARNING",
                    f"Dataset '{ds}' already claimed by '{dataset_repo_map[ds]}', "
                    f"also claimed by '{repo_name}' — keeping first",
                    dataset=ds)
            else:
                dataset_repo_map[ds] = repo_name

    log("INFO", f"Mapped {len(dataset_repo_map)} dataset(s) across {repos_found} repo(s)")
    return dataset_repo_map


def write_to_gcs(data: dict, gcs_uri: str) -> None:
    """Write JSON to a GCS URI (gs://bucket/path/to/file.json)."""
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"--gcs-output must start with gs://, got: {gcs_uri}")
    without_scheme = gcs_uri[5:]
    bucket_name, _, blob_name = without_scheme.partition("/")
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(
        json.dumps(data, indent=2, sort_keys=True),
        content_type="application/json",
    )
    log("INFO", f"Written {len(data)} entries to {gcs_uri}", gcs_uri=gcs_uri)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace-root", default="/workspace/repos/fastossb",
                        help="Root directory of cloned repos (default: /workspace/repos/fastossb)")
    parser.add_argument("--subgroup", default="ndl_core",
                        help="Subgroup folder inside workspace-root (default: ndl_core)")
    parser.add_argument("--gcs-output", required=True,
                        help="GCS URI to write the JSON mapping, "
                             "e.g. gs://my-bucket/dataset-mapping/dataset_repo_map.json")
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root)
    log("INFO", "Starting dataset mapping generation",
        workspace_root=str(workspace_root), subgroup=args.subgroup,
        gcs_output=args.gcs_output)

    dataset_repo_map = build_dataset_repo_map(workspace_root, args.subgroup)
    write_to_gcs(dataset_repo_map, args.gcs_output)
    log("INFO", "Dataset mapping job completed successfully")


if __name__ == "__main__":
    main()
