param(
  [string]$GitLabBaseUrl = "https://dot-portal.de.pri.o2.com/gitlab",
  [string]$GroupPath = "fastoss_b",
  [string]$TargetDir = $(if ($env:REPO_ROOT) { $env:REPO_ROOT } else { "/workspace/repos/fastossb" }),
  [ValidateSet("ssh","https")]
  [string]$CloneProtocol = "https",
  [switch]$HardReset,
  [switch]$SkipWorkspace
)

$ErrorActionPreference = "Stop"

$token = $env:GITLAB_TOKEN
if (-not $token) {
  Write-Error "GITLAB_TOKEN is not set. Please set it to a PAT with read_api + read_repository."
  exit 1
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Error "git not found in PATH. Please install Git."
  exit 1
}


if ($HardReset) {
  git -C $dest reset --hard "origin/$defaultBranch"
  git -C $dest clean -fd
}

git config --global --add safe.directory '*'

$TargetDir = [System.IO.Path]::GetFullPath($TargetDir)

$headers = @{ "PRIVATE-TOKEN" = $token }
$groupEncoded = [uri]::EscapeDataString($GroupPath)

# Get group id
$group = Invoke-RestMethod -Headers $headers -Uri "$GitLabBaseUrl/api/v4/groups/$groupEncoded"
$groupId = $group.id

# Fetch all projects (include subgroups)
$projects = @()
$page = 1
while ($true) {
  $uri = "$GitLabBaseUrl/api/v4/groups/$groupId/projects?include_subgroups=true&per_page=100&page=$page"
  $resp = Invoke-RestMethod -Headers $headers -Uri $uri
  if (-not $resp -or $resp.Count -eq 0) { break }
  $projects += $resp
  $page++
}

if ($projects.Count -eq 0) {
  Write-Host "No projects found for group: $GroupPath"
  exit 0
}

# Clone or update
foreach ($proj in $projects) {
  if ($proj.archived -eq $true) { 
     continue 
  }

  $path = $proj.path_with_namespace
  if ($path.StartsWith("$GroupPath/")) {
    $rel = $path.Substring($GroupPath.Length + 1)
  } else {
    $rel = $path
  }

  $dest = Join-Path $TargetDir $rel
  $repoUrl = if ($CloneProtocol -eq "ssh") { $proj.ssh_url_to_repo } else { $proj.http_url_to_repo }
  $defaultBranch = $proj.default_branch

  if (Test-Path (Join-Path $dest ".git")) {
    Write-Host "Updating: $dest"
    git -C $dest fetch --prune
    if ($defaultBranch) {
      git -C $dest show-ref --verify --quiet "refs/remotes/origin/$defaultBranch"
      if ($LASTEXITCODE -ne 0) {
        Write-Host "  Remote branch 'origin/$defaultBranch' not found; skipping update"
        continue
      }

    if ($HardReset) {
       git -C $dest reset --hard "origin/$defaultBranch"
       git -C $dest clean -fd
     }

      $dirty = git -C $dest status --porcelain
      $currentBranch = (git -C $dest rev-parse --abbrev-ref HEAD).Trim()

      if ($HardReset) {
        if ($currentBranch -ne $defaultBranch) {
          Write-Host "  Switching to default branch '$defaultBranch' for hard reset"
          git -C $dest checkout $defaultBranch 2>$null
          if ($LASTEXITCODE -ne 0) {
            git -C $dest checkout -B $defaultBranch "origin/$defaultBranch"
          }
        }

        Write-Host "  Hard resetting to origin/$defaultBranch"
        git -C $dest reset --hard "origin/$defaultBranch"
        git -C $dest clean -fd
        continue
      }

      if ($dirty) {
        Write-Host "  Skipping refresh (working tree not clean). Use -HardReset to override local changes."
        continue
      }

      if ($currentBranch -ne $defaultBranch) {
        Write-Host "  Skipping refresh (current branch is '$currentBranch', default is '$defaultBranch'). Use -HardReset to override."
        continue
      }

      $aheadBehind = git -C $dest rev-list --left-right --count "origin/$defaultBranch...$defaultBranch"
      if ($LASTEXITCODE -ne 0) {
        Write-Host "  Unable to compare local and remote branch state; skipping refresh."
        continue
      }
      $parts = ($aheadBehind -split '\s+')
      $remoteAhead = if ($parts.Count -ge 1) { [int]$parts[0] } else { 0 }
      $localAhead = if ($parts.Count -ge 2) { [int]$parts[1] } else { 0 }

      if ($localAhead -gt 0) {
        Write-Host "  Skipping refresh (local branch is ahead of origin/$defaultBranch). Use -HardReset to override."
        continue
      }

      if ($remoteAhead -eq 0 -and $localAhead -eq 0) {
        Write-Host "  Already up to date"
        continue
      }

      git -C $dest merge --ff-only "origin/$defaultBranch"
      if ($LASTEXITCODE -ne 0) {
        Write-Host "  Fast-forward failed. Manual update required or rerun with -HardReset."
      }
    } else {
      Write-Host "  No default branch reported; skipping pull"
    }
  } else {
    Write-Host "Cloning: $repoUrl -> $dest"
    New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
    git clone $repoUrl $dest
  }
}

if (-not $SkipWorkspace) {

# Create VS Code workspace
$workspaceFile = Join-Path $TargetDir "fastoss_b.code-workspace"
$folders = @()
foreach ($proj in $projects) {
  if ($proj.archived -eq $true) { 
     continue 
  }
  $path = $proj.path_with_namespace
  if ($path.StartsWith("$GroupPath/")) {
    $rel = $path.Substring($GroupPath.Length + 1)
  } else {
    $rel = $path
  }
  $folders += @{ path = (Join-Path $TargetDir $rel) }
 }
}

@{
  folders = $folders
} | ConvertTo-Json -Depth 4 | Set-Content -Path $workspaceFile -Encoding UTF8

Write-Host "Done. Workspace file: $workspaceFile"
