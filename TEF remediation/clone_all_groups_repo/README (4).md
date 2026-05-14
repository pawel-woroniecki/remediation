# clone_fastoss_b.ps1

Clones or updates all repositories under the `fastoss_b` GitLab group, including subgroups.
It also generates a `fastoss_b.code-workspace` file in the target directory for VS Code.

## Prerequisites

- `git` available in PATH
- A GitLab personal access token (PAT) in `GITLAB_TOKEN` with:
  - `read_api`
  - `read_repository`

## How To Run

From the repo root:

```powershell
./tools/clone_all_groups_repo/clone_fastoss_b.ps1
```

### Optional parameters

- `-TargetDir` (default: `C:\repos\fastossb`)
- `-CloneProtocol` (`ssh` or `https`, default: `ssh`)
- `-GitLabBaseUrl`
- `-GroupPath`
- `-HardReset` hard-resets existing repos to `origin/<default_branch>` and removes untracked files

Examples:

```powershell
# Use HTTPS cloning
./tools/clone_all_groups_repo/clone_fastoss_b.ps1 -CloneProtocol https

# Clone into a specific folder
./tools/clone_all_groups_repo/clone_fastoss_b.ps1 -TargetDir ..\fastossb

# Override local changes and force all existing repos to match origin
./tools/clone_all_groups_repo/clone_fastoss_b.ps1 -HardReset
```

## Notes

- Default refresh mode skips repos with local changes, a non-default checked out branch, or local commits ahead of origin.
- `-HardReset` uses `git reset --hard` and `git clean -fd`, so local uncommitted changes and untracked files are removed.
- The workspace file is written as `fastoss_b.code-workspace` under the target directory.
