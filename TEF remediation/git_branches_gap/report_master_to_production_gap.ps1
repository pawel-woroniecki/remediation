param(
  [string]$Root,
  [switch]$Fetch,
  [string]$SourceBranch = "master",
  [string]$TargetBranch = "production",
  [string]$Output = (Join-Path $PSScriptRoot "..\\..\\outputs")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$defaultRoots = @(
  (Join-Path $PSScriptRoot "..\\..\\..\\..\\ndl_core"),
  (Join-Path $PSScriptRoot "..\\..\\..\\ndl_core")
)

if (-not $PSBoundParameters.ContainsKey("Root") -or [string]::IsNullOrWhiteSpace($Root)) {
  # Try the most common shared-workspace layouts first so the report can run
  # without an explicit -Root in the normal repo structure.
  foreach ($candidate in $defaultRoots) {
    if (Test-Path $candidate) {
      $Root = $candidate
      break
    }
  }
  if (-not $Root) {
    $Root = $defaultRoots[0]
  }
}

if (-not (Test-Path $Root)) {
  throw "Root path not found: $Root"
}
if (-not (Test-Path $Output)) {
  New-Item -ItemType Directory -Path $Output -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$sourceLabel = ($SourceBranch -replace '[^A-Za-z0-9._-]', '_')
$targetLabel = ($TargetBranch -replace '[^A-Za-z0-9._-]', '_')
$outFile = Join-Path $Output "branch_gap_report_${sourceLabel}_vs_${targetLabel}_$timestamp.csv"

$repos = Get-ChildItem -Directory $Root | Where-Object { Test-Path (Join-Path $_.FullName '.git') }
$now = Get-Date

if ($Fetch) {
  foreach ($repo in $repos) {
    try {
      # Refresh remote refs before comparison so the report reflects current
      # origin/$SourceBranch and origin/$TargetBranch rather than stale local metadata.
      git -C $repo.FullName fetch origin --prune --quiet | Out-Null
    } catch {
      Write-Warning "Fetch failed for $($repo.Name): $($_.Exception.Message)"
    }
  }
}

$results = foreach ($repo in $repos) {
  $path = $repo.FullName
  $name = $repo.Name
  $sourceRef = "origin/$SourceBranch"
  $targetRef = "origin/$TargetBranch"

  # Compare remote-tracking branches only, so repos without the selected refs
  # can be reported clearly without depending on local branch state.
  git -C $path rev-parse --verify $sourceRef 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) {
    [pscustomobject]@{
      repo                             = $name
      source_branch                    = $SourceBranch
      target_branch                    = $TargetBranch
      target_branch_present            = "unknown"
      source_commits_not_in_target     = "N/A"
      target_commits_not_in_source     = "N/A"
      oldest_source_commit_not_in_target = "N/A"
      waiting_days                     = "N/A"
      last_target_commit               = "N/A"
      last_target_commit_date          = "N/A"
      last_source_commit               = "N/A"
      last_source_commit_date          = "N/A"
      status                           = "no $sourceRef"
    }
    continue
  }

  git -C $path show-ref --verify --quiet "refs/remotes/origin/$TargetBranch"
  $hasTarget = ($LASTEXITCODE -eq 0)

  if (-not $hasTarget) {
    $lastSource = git -C $path log -n 1 --format="%h|%cd" $sourceRef
    $lsParts = if ($lastSource) { $lastSource -split '\|',2 } else { @("", "") }
    [pscustomobject]@{
      repo                             = $name
      source_branch                    = $SourceBranch
      target_branch                    = $TargetBranch
      target_branch_present            = "missing"
      source_commits_not_in_target     = "N/A"
      target_commits_not_in_source     = "N/A"
      oldest_source_commit_not_in_target = "N/A"
      waiting_days                     = "N/A"
      last_target_commit               = "N/A"
      last_target_commit_date          = "N/A"
      last_source_commit               = $lsParts[0]
      last_source_commit_date          = $lsParts[1]
      status                           = "no $targetRef"
    }
    continue
  }

  # rev-list --left-right --count A...B returns:
  # - commits reachable only from A on the left
  # - commits reachable only from B on the right
  # Here that means target-only commits first, then source-only commits.
  $counts = git -C $path rev-list --left-right --count "$targetRef...$sourceRef"
  $parts = ($counts -split '\s+')
  $targetAhead = [int]$parts[0]
  $sourceAhead = [int]$parts[1]

  $oldestStr = ""
  $days = 0
  if ($sourceAhead -gt 0) {
    # Take the oldest commit that exists on source but not target to show
    # how long the current sync lag has been waiting.
    $oldest = git -C $path log --reverse --format="%ct|%cd" "$targetRef..$sourceRef" -n 1
    if ($oldest) {
      $oparts = $oldest -split '\|',2
      $ts = [int64]$oparts[0]
      $date = [DateTimeOffset]::FromUnixTimeSeconds($ts).LocalDateTime
      $oldestStr = $date.ToString("yyyy-MM-dd")
      $days = [math]::Floor((New-TimeSpan -Start $date -End $now).TotalDays)
    }
  }

  $lastTarget = git -C $path log -n 1 --format="%h|%cd" $targetRef
  $ltParts = if ($lastTarget) { $lastTarget -split '\|',2 } else { @("", "") }

  $lastSource = git -C $path log -n 1 --format="%h|%cd" $sourceRef
  $lsParts = if ($lastSource) { $lastSource -split '\|',2 } else { @("", "") }

  # Any source-only commits mean the target branch is behind the branch that
  # is expected to flow into it.
  $status = if ($sourceAhead -eq 0) { "in sync" } else { "waiting for sync" }

  [pscustomobject]@{
    repo                             = $name
    source_branch                    = $SourceBranch
    target_branch                    = $TargetBranch
    target_branch_present            = "yes"
    source_commits_not_in_target     = $sourceAhead
    target_commits_not_in_source     = $targetAhead
    oldest_source_commit_not_in_target = $(if ($oldestStr) { $oldestStr } else { "" })
    waiting_days                     = $(if ($sourceAhead -gt 0) { $days } else { 0 })
    last_target_commit               = $ltParts[0]
    last_target_commit_date          = $ltParts[1]
    last_source_commit               = $lsParts[0]
    last_source_commit_date          = $lsParts[1]
    status                           = $status
  }
}

$results | Sort-Object repo | Tee-Object -Variable sorted | Format-Table -AutoSize

try {
  $sorted | Export-Csv -NoTypeInformation -Path $outFile
  Write-Host "\nReport saved to $outFile"
} catch {
  Write-Warning "Failed to write CSV: $($_.Exception.Message)"
}
