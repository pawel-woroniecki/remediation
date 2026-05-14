param(
  [string]$Root = 'c:\repos\fastossb\ndl_core',
  [string]$DateTag = (Get-Date -Format 'yyyy-MM-dd'),
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\\..\\outputs")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $OutputDir)) {
  New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$log = Join-Path $OutputDir "branch_refresh_status_$DateTag.csv"
$repos = Get-ChildItem -Directory $Root | Where-Object { Test-Path (Join-Path $_.FullName '.git') } | Sort-Object Name
$rows = @()
$repoCount = @($repos).Count
$repoIndex = 0

Write-Host "[sync_remote_branches] Starting refresh"
Write-Host "[sync_remote_branches] Root=$Root DateTag=$DateTag OutputDir=$OutputDir"
Write-Host "[sync_remote_branches] We will process $repoCount projects"

foreach($r in $repos){
  $repoIndex++
  $path = $r.FullName
  $name = $r.Name
  $status = 'ok'
  $notes = @()

  Write-Host "[sync_remote_branches] Project $repoIndex/${repoCount}: $name"

  try {
    git -C $path fetch origin --prune --quiet 2>$null
    git -C $path reset --hard --quiet 2>$null
    git -C $path clean -fd -q 2>$null

    foreach($b in @('master','test','production')){
      git -C $path show-ref --verify --quiet "refs/remotes/origin/$b" 2>$null
      if($LASTEXITCODE -ne 0){
        $notes += "origin/$b missing"
        continue
      }

      git -C $path show-ref --verify --quiet "refs/heads/$b" 2>$null
      if($LASTEXITCODE -eq 0){
        git -C $path checkout --quiet $b 2>$null
      } else {
        git -C $path checkout --quiet -B $b "origin/$b" 2>$null
      }
      git -C $path reset --hard --quiet "origin/$b" 2>$null
    }

    if($notes -notcontains 'origin/master missing'){
      git -C $path checkout --quiet master 2>$null
    }
  } catch {
    $status = 'error'
    $notes += $_.Exception.Message
  }

  $rows += [pscustomobject]@{
    repo = $name
    status = $status
    notes = ($notes -join '; ')
  }
}

$rows | Export-Csv -Path $log -NoTypeInformation -Encoding UTF8
Write-Host "REFRESH_LOG=$log"
Write-Host "[sync_remote_branches] Finished"

