#!/usr/bin/env python3
"""
Reorganize gcloud bulk-export Terraform files into a folder hierarchy that
mirrors GitLab repositories.

Each GitLab repo in fastoss_b/ndl_core declares BQ_DATASET_NAMES in its
.gitlab-ci.yml.  This script reads those declarations via the GitLab API
(token fetched from GCP Secret Manager — no manual token handling needed),
then walks the local tf_export_* directories and copies each .tf file into:

    {output_dir}/{env}/{repo_name}/{BigQueryDataset|BigQueryTable|BigQueryRoutine}/...

Files whose dataset is not claimed by any repo land in:

    {output_dir}/{env}/_unmapped/{resource_type}/...

Usage (from Cloud Shell):
    # Process all environments
    python organize_tf_export.py --gcp-project tefde-gcp-fastoss-dev-gke

    # Process a single environment
    python organize_tf_export.py --gcp-project tefde-gcp-fastoss-dev-gke --env prod-gke

    # Process several environments
    python organize_tf_export.py --gcp-project tefde-gcp-fastoss-dev-gke --env prod,prod-gke

All options:
    --gcp-project    ID      GCP project that holds the GitLab PAT in Secret Manager (required)
    --secret-id      ID      Secret Manager secret ID (default: gitlab-token)
    --gitlab-url     URL     GitLab base URL (default: https://dot-portal.de.pri.o2.com/gitlab)
    --base-dir       PATH    Parent of tf_export_* dirs (default: /home/nq10083194)
    --output-dir     PATH    Destination root (default: {base_dir}/terraform-export-by-repos)
    --env / --envs   LIST    Comma-separated envs to process
                             (default: prod,prod-gke,test,test-gke,dev,dev-gke)
    --dry-run                Print what would be copied without copying
"""

import argparse
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

import subprocess

import requests
import yaml

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITLAB_GROUP = "fastoss_b/ndl_core"
GITLAB_CI_FILE = ".gitlab-ci.yml"
BRANCHES_TO_TRY = ["production", "master"]
DEFAULT_GITLAB_URL = "https://dot-portal.de.pri.o2.com/gitlab"

ENV_TO_PROJECT = {
    "prod":     "tefde-gcp-fastoss-prod",
    "prod-gke": "tefde-gcp-fastoss-prod-gke",
    "test":     "tefde-gcp-fastoss-test",
    "test-gke": "tefde-gcp-fastoss-test-gke",
    "dev":      "tefde-gcp-fastoss-dev",
    "dev-gke":  "tefde-gcp-fastoss-dev-gke",
}

RESOURCE_TYPES = ["BigQueryDataset", "BigQueryTable", "BigQueryRoutine"]


# ---------------------------------------------------------------------------
# Secret Manager
# ---------------------------------------------------------------------------

def get_gitlab_token(gcp_project: str, secret_id: str) -> str:
    """Fetch the GitLab PAT from GCP Secret Manager via gcloud CLI."""
    result = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest",
         f"--secret={secret_id}", f"--project={gcp_project}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR fetching secret '{secret_id}' from project '{gcp_project}':")
        print(result.stderr.strip())
        print("\nHint: if your account lacks secretmanager.versions.access, pass the token "
              "directly with --gitlab-token TOKEN (or set env var GITLAB_TOKEN).")
        sys.exit(1)
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# GitLab helpers
# ---------------------------------------------------------------------------

def _gitlab_get(session: requests.Session, url: str, **params) -> list[dict]:
    """GET a paginated GitLab API endpoint and return all items."""
    items: list[dict] = []
    params.setdefault("per_page", 100)
    while url:
        resp = session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        items.extend(resp.json())
        url = resp.links.get("next", {}).get("url")
        params = {}  # pagination URL already encodes params
    return items


def list_group_projects(session: requests.Session, gitlab_url: str) -> list[dict]:
    group_enc = quote(GITLAB_GROUP, safe="")
    url = f"{gitlab_url}/api/v4/groups/{group_enc}/projects"
    projects = _gitlab_get(session, url, include_subgroups="false", archived="false")
    print(f"  Found {len(projects)} project(s) in {GITLAB_GROUP}")
    return projects


def fetch_ci_yaml(session: requests.Session, gitlab_url: str, project_id: int) -> dict | None:
    """Fetch and parse .gitlab-ci.yml for a project, trying multiple branches."""
    file_enc = quote(GITLAB_CI_FILE, safe="")
    for branch in BRANCHES_TO_TRY:
        url = f"{gitlab_url}/api/v4/projects/{project_id}/repository/files/{file_enc}/raw"
        try:
            resp = session.get(url, params={"ref": branch}, timeout=30)
            if resp.status_code == 200:
                return yaml.safe_load(resp.text) or {}
        except Exception:
            pass
    return None


def build_dataset_repo_map(session: requests.Session, gitlab_url: str) -> dict[str, str]:
    """Return {dataset_name: repo_name} from BQ_DATASET_NAMES in each repo's CI file."""
    print("\n=== Phase 1: Reading GitLab repositories ===")
    projects = list_group_projects(session, gitlab_url)

    dataset_repo_map: dict[str, str] = {}
    repos_with_datasets = 0

    for project in projects:
        name = project["path"]  # short project name, e.g. "auxiliary"
        pid = project["id"]
        ci = fetch_ci_yaml(session, gitlab_url, pid)
        if ci is None:
            print(f"  [{name}] .gitlab-ci.yml not found on branches {BRANCHES_TO_TRY}")
            continue

        raw = ci.get("variables", {}).get("BQ_DATASET_NAMES", "")
        if not raw:
            continue

        datasets = [d.strip() for d in str(raw).split(",") if d.strip()]
        repos_with_datasets += 1
        print(f"  [{name}] {len(datasets)} dataset(s): {', '.join(datasets)}")

        for ds in datasets:
            if ds in dataset_repo_map:
                print(f"  WARNING: dataset '{ds}' already claimed by "
                      f"'{dataset_repo_map[ds]}', also claimed by '{name}' — keeping first")
            else:
                dataset_repo_map[ds] = name

    print(f"\n  Total: {repos_with_datasets} repo(s) → {len(dataset_repo_map)} dataset mapping(s)")
    return dataset_repo_map


# ---------------------------------------------------------------------------
# Export walking helpers
# ---------------------------------------------------------------------------

def _iter_resource_roots(base_dir: Path, env: str, project_id: str):
    """Yield (resource_type, root_path) for all candidate roots that exist."""
    export_dir = base_dir / f"tf_export_{env}"
    if not export_dir.exists():
        print(f"  [SKIP] Export dir not found: {export_dir}")
        return

    # Two path conventions used by gcloud bulk-export:
    candidate_prefixes = [
        export_dir / project_id,
        export_dir / "projects" / project_id,
    ]
    for prefix in candidate_prefixes:
        for rtype in RESOURCE_TYPES:
            candidate = prefix / rtype
            if candidate.exists():
                yield rtype, candidate


def dataset_from_path(rtype: str, rel: Path) -> str:
    """Extract the BQ dataset name from a relative path within a resource-type folder."""
    parts = rel.parts
    if rtype == "BigQueryDataset":
        # .../europe-west3/{dataset_name}.tf  OR  .../{dataset_name}.tf
        return rel.stem
    else:
        # BigQueryTable/{dataset_name}/{table_name}.tf
        # BigQueryRoutine/{dataset_name}/{routine_name}.tf
        return parts[0] if parts else ""


def collect_tf_files(base_dir: Path, env: str, project_id: str) -> list[tuple[str, str, Path]]:
    """Return list of (resource_type, dataset_name, absolute_path) for every .tf file."""
    results = []
    seen_roots: set[Path] = set()
    for rtype, root in _iter_resource_roots(base_dir, env, project_id):
        if root in seen_roots:
            continue
        seen_roots.add(root)
        for tf_file in sorted(root.rglob("*.tf")):
            rel = tf_file.relative_to(root)
            ds = dataset_from_path(rtype, rel)
            if ds:
                results.append((rtype, ds, tf_file))
    return results


# ---------------------------------------------------------------------------
# Copy logic
# ---------------------------------------------------------------------------

def copy_file(src: Path, dst: Path, dry_run: bool) -> bool:
    """Copy src to dst.  Return True if the file was (would be) copied."""
    if dst.exists():
        src_stat = src.stat()
        dst_stat = dst.stat()
        if src_stat.st_size == dst_stat.st_size and abs(src_stat.st_mtime - dst_stat.st_mtime) < 1:
            return False  # identical — skip
    if dry_run:
        print(f"    [DRY-RUN] {src} → {dst}")
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def process_env(
    env: str,
    project_id: str,
    base_dir: Path,
    output_dir: Path,
    dataset_repo_map: dict[str, str],
    dry_run: bool,
) -> dict[str, int]:
    """Walk one environment's export and copy files to the output tree."""
    tf_files = collect_tf_files(base_dir, env, project_id)
    if not tf_files:
        print(f"  [SKIP] No .tf files found for env={env} project={project_id}")
        return {}

    counts: dict[str, int] = defaultdict(int)
    env_out = output_dir / env

    for rtype, ds_name, src in tf_files:
        repo = dataset_repo_map.get(ds_name, "_unmapped")

        # Compute destination path, preserving sub-folder structure within the resource type.
        # Find which root the file lives under so we can compute the relative tail.
        for _, root in _iter_resource_roots(base_dir, env, project_id):
            try:
                rel_tail = src.relative_to(root)
                break
            except ValueError:
                continue
        else:
            rel_tail = Path(src.name)

        dst = env_out / repo / rtype / rel_tail
        copied = copy_file(src, dst, dry_run)
        if copied:
            counts[repo] += 1

    return counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--gitlab-token",
        default=os.environ.get("GITLAB_TOKEN"),
        metavar="TOKEN",
        help="GitLab PAT (overrides Secret Manager lookup). "
             "Also accepted via env var GITLAB_TOKEN.",
    )
    parser.add_argument(
        "--gcp-project",
        default=None,
        help="GCP project ID used to look up the GitLab PAT in Secret Manager. "
             "Required unless --gitlab-token is provided.",
    )
    parser.add_argument(
        "--secret-id", default="gitlab-token",
        help="Secret Manager secret ID that holds the GitLab PAT (default: gitlab-token)",
    )
    parser.add_argument(
        "--gitlab-url", default=DEFAULT_GITLAB_URL,
        help=f"GitLab base URL (default: {DEFAULT_GITLAB_URL})",
    )
    parser.add_argument(
        "--base-dir", default="/home/nq10083194",
        help="Parent of tf_export_* dirs (default: /home/nq10083194)",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Output root (default: {base_dir}/terraform-export-by-repos)",
    )
    # --env and --envs are aliases for the same parameter
    env_group = parser.add_mutually_exclusive_group()
    env_group.add_argument(
        "--env",
        dest="envs",
        default=None,
        metavar="ENV[,ENV...]",
        help="Comma-separated env(s) to process, e.g. prod-gke or prod,prod-gke "
             "(default: all six)",
    )
    env_group.add_argument(
        "--envs",
        dest="envs",
        default=None,
        metavar="ENV[,ENV...]",
        help="Alias for --env",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print planned copies without writing files")
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    output_dir = Path(args.output_dir) if args.output_dir else base_dir / "terraform-export-by-repos"
    envs_raw = args.envs if args.envs else ",".join(ENV_TO_PROJECT)
    envs = [e.strip() for e in envs_raw.split(",") if e.strip()]

    unknown_envs = [e for e in envs if e not in ENV_TO_PROJECT]
    if unknown_envs:
        print(f"ERROR: unknown env(s): {unknown_envs}. Valid: {list(ENV_TO_PROJECT)}")
        sys.exit(1)

    # Resolve GitLab token — direct flag takes priority over Secret Manager
    if args.gitlab_token:
        token = args.gitlab_token
        print("Using GitLab token from --gitlab-token / GITLAB_TOKEN.")
    elif args.gcp_project:
        print(f"Fetching GitLab token from Secret Manager "
              f"(project={args.gcp_project}, secret={args.secret_id}) ...")
        token = get_gitlab_token(args.gcp_project, args.secret_id)
    else:
        print("ERROR: provide either --gitlab-token TOKEN or --gcp-project PROJECT_ID")
        sys.exit(1)

    session = requests.Session()
    session.headers["PRIVATE-TOKEN"] = token

    # Phase 1: build dataset → repo mapping from GitLab
    dataset_repo_map = build_dataset_repo_map(session, args.gitlab_url.rstrip("/"))

    # Phase 2: walk each env and copy files
    print(f"\n=== Phase 2: Copying Terraform files ({'DRY-RUN' if args.dry_run else 'LIVE'}) ===")
    print(f"  Environments : {', '.join(envs)}")
    print(f"  Output dir   : {output_dir}\n")

    grand_total = 0
    for env in envs:
        project_id = ENV_TO_PROJECT[env]
        print(f"[{env}] → {project_id}")
        counts = process_env(env, project_id, base_dir, output_dir, dataset_repo_map, args.dry_run)
        env_total = sum(counts.values())
        grand_total += env_total
        unmapped = counts.pop("_unmapped", 0)
        for repo, n in sorted(counts.items()):
            print(f"  {repo}: {n} file(s)")
        if unmapped:
            print(f"  _unmapped: {unmapped} file(s)  ← no GitLab repo claims these datasets")
        print(f"  Subtotal: {env_total} file(s)\n")

    print(f"{'[DRY-RUN] ' if args.dry_run else ''}Done. {grand_total} file(s) total.")


if __name__ == "__main__":
    main()
