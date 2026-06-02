#!/usr/bin/env python3
"""Clone or update all non-archived projects in a GitLab group (including subgroups).

Auth: reads the GitLab PAT from GCP Secret Manager — no environment variable
required for the token itself.  The GCP project and secret ID are passed as
CLI arguments (defaults: --gcp-project required, --secret-id gitlab-token).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from google.cloud import secretmanager


# ---------------------------------------------------------------------------
# Secret Manager
# ---------------------------------------------------------------------------

def get_gitlab_token(gcp_project: str, secret_id: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{gcp_project}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8").strip()


# ---------------------------------------------------------------------------
# GitLab API helpers
# ---------------------------------------------------------------------------

def api_get(base_url: str, path: str, token: str, params: dict | None = None) -> dict | list:
    resp = requests.get(
        f"{base_url}/api/v4/{path}",
        headers={"PRIVATE-TOKEN": token},
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_all_projects(base_url: str, group_id: int, token: str) -> list[dict]:
    projects: list[dict] = []
    page = 1
    while True:
        page_data = api_get(
            base_url,
            f"groups/{group_id}/projects",
            token,
            params={"include_subgroups": "true", "per_page": 100, "page": page},
        )
        if not page_data:
            break
        projects.extend(page_data)
        page += 1
    return projects


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def inject_token(clone_url: str, token: str) -> str:
    """Embed oauth2 credentials into an HTTPS clone URL."""
    p = urlparse(clone_url)
    port_part = f":{p.port}" if p.port else ""
    netloc = f"oauth2:{token}@{p.hostname}{port_part}"
    return p._replace(netloc=netloc).geturl()


def _git(args: list[str], cwd: str | None = None) -> int:
    result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    if result.stderr:
        # Redact oauth2 tokens from git error output before it reaches logs.
        redacted = re.sub(r"oauth2:[^@]+@", "oauth2:***@", result.stderr)
        print(redacted, end="", file=sys.stderr)
    return result.returncode


def _git_out(args: list[str], cwd: str | None = None) -> str:
    return subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True
    ).stdout.strip()


def clone_or_update(dest: Path, repo_url: str, default_branch: str | None, hard_reset: bool) -> None:
    if (dest / ".git").exists():
        print(f"Updating: {dest}")
        _git(["-C", str(dest), "fetch", "--prune"])

        if not default_branch:
            print("  No default branch reported; skipping pull")
            return

        rc = _git(["-C", str(dest), "show-ref", "--verify", "--quiet",
                   f"refs/remotes/origin/{default_branch}"])
        if rc != 0:
            print(f"  Remote branch 'origin/{default_branch}' not found; skipping update")
            return

        if hard_reset:
            current = _git_out(["-C", str(dest), "rev-parse", "--abbrev-ref", "HEAD"])
            if current != default_branch:
                print(f"  Switching to '{default_branch}' for hard reset")
                if _git(["-C", str(dest), "checkout", default_branch]) != 0:
                    _git(["-C", str(dest), "checkout", "-B", default_branch,
                          f"origin/{default_branch}"])
            print(f"  Hard resetting to origin/{default_branch}")
            _git(["-C", str(dest), "reset", "--hard", f"origin/{default_branch}"])
            _git(["-C", str(dest), "clean", "-fd"])
            return

        dirty = _git_out(["-C", str(dest), "status", "--porcelain"])
        if dirty:
            print("  Skipping refresh (working tree not clean). "
                  "Use --hard-reset to override local changes.")
            return

        current = _git_out(["-C", str(dest), "rev-parse", "--abbrev-ref", "HEAD"])
        if current != default_branch:
            print(f"  Skipping refresh (on '{current}', default is '{default_branch}'). "
                  "Use --hard-reset to override.")
            return

        result = subprocess.run(
            ["git", "-C", str(dest), "rev-list", "--left-right", "--count",
             f"origin/{default_branch}...{default_branch}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print("  Unable to compare local and remote branch state; skipping refresh.")
            return

        parts = result.stdout.strip().split()
        remote_ahead = int(parts[0]) if len(parts) >= 1 else 0
        local_ahead  = int(parts[1]) if len(parts) >= 2 else 0

        if local_ahead > 0:
            print(f"  Skipping refresh (local is ahead of origin/{default_branch}). "
                  "Use --hard-reset to override.")
            return
        if remote_ahead == 0:
            print("  Already up to date")
            return

        rc = _git(["-C", str(dest), "merge", "--ff-only", f"origin/{default_branch}"])
        if rc != 0:
            print("  Fast-forward failed. Manual update required or rerun with --hard-reset.")
    else:
        # Hide token from log output
        safe_url = repo_url.split("@")[-1] if "@" in repo_url else repo_url
        print(f"Cloning: {safe_url} -> {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", repo_url, str(dest)])
        # Strip credentials from the remote URL so the token is not stored in .git/config
        clean_url = repo_url.split("@")[-1] if "@" in repo_url else repo_url
        clean_url = f"{urlparse(repo_url).scheme}://{clean_url}"
        _git(["-C", str(dest), "remote", "set-url", "origin", clean_url])


# ---------------------------------------------------------------------------
# VS Code workspace
# ---------------------------------------------------------------------------

def write_vscode_workspace(target_dir: Path, projects: list[dict], group_path: str) -> None:
    folders = []
    for proj in projects:
        if proj.get("archived"):
            continue
        path = proj["path_with_namespace"]
        rel = path[len(group_path) + 1:] if path.startswith(f"{group_path}/") else path
        folders.append({"path": str(target_dir / rel)})
    workspace_file = target_dir / "fastoss_b.code-workspace"
    workspace_file.write_text(json.dumps({"folders": folders}, indent=2), encoding="utf-8")
    print(f"Workspace file written: {workspace_file}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clone or update all projects in a GitLab group."
    )
    parser.add_argument(
        "--gitlab-base-url",
        default="https://dot-portal.de.pri.o2.com/gitlab",
    )
    parser.add_argument("--group-path", default="fastoss_b")
    parser.add_argument(
        "--target-dir",
        default=os.environ.get("REPO_ROOT", "/workspace/repos/fastossb"),
    )
    parser.add_argument(
        "--clone-protocol", choices=["ssh", "https"], default="https"
    )
    parser.add_argument("--hard-reset", action="store_true")
    parser.add_argument("--skip-workspace", action="store_true")
    parser.add_argument(
        "--gcp-project",
        required=True,
        help="GCP project ID used to look up the GitLab PAT in Secret Manager.",
    )
    parser.add_argument(
        "--secret-id",
        default="gitlab-token",
        help="Secret Manager secret ID that holds the GitLab PAT.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    print(f"[clone] Fetching GitLab token from Secret Manager "
          f"(project={args.gcp_project}, secret={args.secret_id}) ...")
    token = get_gitlab_token(args.gcp_project, args.secret_id)

    _git(["config", "--global", "--add", "safe.directory", "*"])

    target_dir = Path(args.target_dir).resolve()
    group_encoded = quote(args.group_path, safe="")

    print(f"[clone] Resolving group '{args.group_path}' ...")
    group = api_get(args.gitlab_base_url, f"groups/{group_encoded}", token)
    group_id = group["id"]

    print(f"[clone] Fetching project list for group ID {group_id} ...")
    all_projects = get_all_projects(args.gitlab_base_url, group_id, token)
    active_projects = [p for p in all_projects if not p.get("archived")]
    print(f"[clone] Found {len(active_projects)} non-archived project(s)")

    if not active_projects:
        print(f"[clone] No projects found for group: {args.group_path}")
        return 0

    for proj in active_projects:
        path = proj["path_with_namespace"]
        rel = (path[len(args.group_path) + 1:]
               if path.startswith(f"{args.group_path}/") else path)
        dest = target_dir / rel
        default_branch = proj.get("default_branch")

        if args.clone_protocol == "ssh":
            repo_url = proj["ssh_url_to_repo"]
        else:
            repo_url = inject_token(proj["http_url_to_repo"], token)

        clone_or_update(dest, repo_url, default_branch, args.hard_reset)

    if not args.skip_workspace:
        write_vscode_workspace(target_dir, active_projects, args.group_path)

    print("[clone] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
