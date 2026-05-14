# clone_fastoss_b

Clones or updates all non-archived repositories under the `fastoss_b` GitLab group, including subgroups.

Two versions exist:

| Script | Language | Used by | Auth |
|---|---|---|---|
| `clone_fastoss_b.py` | Python | Cloud Run Jobs (via `entrypoint.sh`) | PAT from GCP Secret Manager |
| `clone_fastoss_b.ps1` | PowerShell | Local developer use | `GITLAB_TOKEN` env var |

---

## Python script (Cloud Run)

### How it works

1. Fetches the GitLab PAT from **GCP Secret Manager**
2. Calls the GitLab REST API to enumerate all projects in the group
3. Clones or fast-forward updates each non-archived repo using HTTPS
4. Optionally writes a `fastoss_b.code-workspace` file for VS Code

### Prerequisites

- `git` available in PATH
- GCP Application Default Credentials with access to Secret Manager

### Parameters

| Argument | Default | Description |
|---|---|---|
| `--gcp-project` | *(required)* | GCP project ID where the Secret Manager secret lives |
| `--secret-id` | `gitlab-token` | Secret Manager secret ID containing the GitLab PAT |
| `--gitlab-base-url` | `https://dot-portal.de.pri.o2.com/gitlab` | GitLab instance base URL |
| `--group-path` | `fastoss_b` | Top-level GitLab group to clone |
| `--target-dir` | `$REPO_ROOT` or `/workspace/repos/fastossb` | Local directory to clone into |
| `--clone-protocol` | `https` | `https` or `ssh` |
| `--hard-reset` | false | Reset existing repos to `origin/<default_branch>` |
| `--skip-workspace` | false | Skip writing the VS Code workspace file |

### Example

```bash
python clone_fastoss_b.py \
  --gcp-project tefde-gcp-fastoss-dev-gke \
  --secret-id gitlab-token \
  --target-dir /workspace/repos/fastossb \
  --skip-workspace
```

---

## PowerShell script (local dev)

### Prerequisites

- PowerShell 5+ or 7+
- `git` available in PATH
- `GITLAB_TOKEN` environment variable set to a PAT with `read_api` + `read_repository` scopes

### Parameters

| Parameter | Default | Description |
|---|---|---|
| `-TargetDir` | `C:\repos\fastossb` | Local directory to clone into |
| `-CloneProtocol` | `https` | `ssh` or `https` |
| `-GitLabBaseUrl` | `https://dot-portal.de.pri.o2.com/gitlab` | GitLab instance URL |
| `-GroupPath` | `fastoss_b` | Top-level GitLab group |
| `-HardReset` | false | Reset repos to `origin/<default_branch>` |
| `-SkipWorkspace` | false | Skip VS Code workspace file |

### Examples

```powershell
# Standard clone
.\clone_fastoss_b.ps1

# Force all repos to match remote
.\clone_fastoss_b.ps1 -HardReset

# Clone into a custom folder using HTTPS
.\clone_fastoss_b.ps1 -TargetDir ..\fastossb -CloneProtocol https
```

---

## Notes

- Archived projects are skipped automatically.
- Default update mode skips repos that have local changes, a non-default branch checked out, or local commits ahead of origin. Use `--hard-reset` / `-HardReset` to override.
- The GitLab PAT requires `read_api` and `read_repository` scopes. For production use, prefer a **Group Access Token** over a Personal Access Token so the secret is not tied to an individual user account.
