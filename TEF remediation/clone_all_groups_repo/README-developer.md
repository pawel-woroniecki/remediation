# Developer Guide — `clone_fastoss_b.py`

This document explains the internal design of the GitLab clone/update script for
developers who need to maintain, extend, or debug it.
For operational use (parameters, examples) see [README.md](README.md).

---

## Purpose

The script clones or refreshes all non-archived GitLab projects in a group
(including all subgroups) into a local directory structure that mirrors the
GitLab namespace. It is the **first step** of every Cloud Run Job pipeline:
the other scripts (`report_branch_discrepancies_by_content.py`,
`generate_code_environment_drift_report.py`, etc.) all operate on locally
cloned repos that this script prepares.

---

## High-Level Flow

```
Secret Manager
   │
   └─ get_gitlab_token()       ← PAT from GCP Secret Manager
         │
         ▼
GitLab REST API
   │
   ├─ api_get(groups/{id})     ← resolve group path → group ID
   └─ get_all_projects()       ← paginated list of all projects in group
         │
         ▼
for each non-archived project:
   clone_or_update(dest, url, default_branch, hard_reset)
         │
         ├─ NEW repo  → git clone -b <branch> <url> <dest>
         │              git remote set-url origin <clean_url>   ← strip token
         │
         └─ EXISTING  → git fetch --prune
                         (various safety guards — see below)
                         git merge --ff-only origin/<branch>
         │
         ▼
write_vscode_workspace()       ← .code-workspace file (optional)
```

---

## Key Functions

### `get_gitlab_token(gcp_project, secret_id)`

Reads the GitLab Personal Access Token from GCP Secret Manager using the
`secretmanager` Python SDK. Accesses the `latest` version of the secret.
The token is never written to disk or logged — it is held in memory for the
duration of the run.

### `inject_token(clone_url, token)`

Embeds `oauth2:<token>@` into the HTTPS clone URL so git can authenticate
without a credential helper. Immediately after cloning, `clone_or_update`
calls `git remote set-url origin <clean_url>` to remove the token from
`.git/config`, preventing it from being persisted on disk.

### `get_all_projects(base_url, group_id, token)`

Calls `GET /api/v4/groups/{id}/projects?include_subgroups=true` with
pagination (`per_page=100`, incrementing `page`) until an empty response is
returned. Returns all projects in the group and every nested subgroup.

### `clone_or_update(dest, repo_url, default_branch, hard_reset)`

The core logic. Behaviour differs depending on whether the repo already exists:

**New repo** (`dest/.git` does not exist):
1. `git clone -b <branch> <url> <dest>`
2. `git remote set-url origin <clean_url>` — strips the embedded token.

**Existing repo** — runs a series of safety guards before pulling:

| Guard | Condition | Action |
|---|---|---|
| Remote branch missing | `origin/<branch>` not in `show-ref` | Skip update |
| Working tree dirty | `git status --porcelain` non-empty | Skip (warn); hard-reset overrides |
| Wrong local branch | `HEAD != default_branch` | Skip (warn); hard-reset overrides |
| Local ahead of remote | `rev-list --left-right` local count > 0 | Skip (warn); hard-reset overrides |
| Already up to date | remote ahead count = 0 | Print "up to date", skip |
| Normal case | remote ahead, local clean, on right branch | `git merge --ff-only origin/<branch>` |

**`--hard-reset` mode** bypasses the dirty/wrong-branch/local-ahead guards:
- Checks out the default branch (or creates it from `origin/<branch>`)
- `git reset --hard origin/<branch>`
- `git clean -fd` — removes untracked files

### `_git(args, cwd)` / `_git_out(args, cwd)`

Thin wrappers around `subprocess.run(["git"] + args)`.
- `_git` returns the exit code; stderr is printed to `sys.stderr` with oauth2
  tokens redacted (`re.sub(r"oauth2:[^@]+@", "oauth2:***@", ...)`).
- `_git_out` returns stdout as a stripped string; used for reading state
  (current branch, ahead/behind counts).

---

## Security Considerations

- The GitLab PAT is read from Secret Manager — never from environment variables
  or files, which would expose it in process listings or Docker image layers.
- The token is embedded in the clone URL transiently and immediately stripped
  from `.git/config` after the clone succeeds.
- `_git` redacts the token from all git stderr output before printing, so it
  does not appear in Cloud Run logs.
- `git config --global --add safe.directory *` is called at startup to allow
  git operations inside the Docker container where the working directory may
  differ from the image user's home.

---

## VS Code Workspace

`write_vscode_workspace()` generates a `fastoss_b.code-workspace` file in the
target directory listing all non-archived repos as workspace folders. This is a
convenience for local development. It is skipped with `--skip-workspace` and is
not needed in Cloud Run.

---

## Relationship to Other Scripts

The clone step is invoked as the `clone` sub-command in `entrypoint.sh`, always
before any drift report sub-command. The `--target-dir` (or `REPO_ROOT` env var)
must match the `--root` argument passed to the drift report scripts.

---

## Extending the Script

**Clone a different group**: pass `--group-path <path>` — the script resolves
it to a group ID via the REST API dynamically.

**Clone a specific branch across all repos**: pass `--branch <name>`. Without it,
each repo uses its GitLab-reported default branch.

**Add SSH support**: already implemented via `--clone-protocol ssh`; the token
injection step is skipped because SSH auth uses keys instead.

---

## Local Development

```bash
python clone_fastoss_b.py \
  --gitlab-base-url https://your-gitlab-host/gitlab \
  --group-path fastoss_b \
  --target-dir /tmp/repos/fastossb \
  --gcp-project tefde-gcp-fastoss-dev \
  --secret-id gitlab-token \
  --branch production
```

Requires `gcloud auth application-default login` for Secret Manager access.
