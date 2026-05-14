param(
  [string]$Root = 'c:\repos\fastossb\ndl_core',
  [string]$DateTag = (Get-Date -Format 'yyyy-MM-dd'),
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\\..\\outputs"),
  [ValidateSet('merge_base','direct')]
  [string]$CompareMode = 'merge_base'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $OutputDir)) {
  New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$outFileCounts = Join-Path $OutputDir "branch_discrepancy_file_counts_prod_master_test_content_$DateTag.csv"
$outDetail     = Join-Path $OutputDir "branch_discrepancy_file_lines_prod_master_test_content_$DateTag.csv"
$outTotals     = Join-Path $OutputDir "branch_discrepancy_file_totals_prod_master_test_content_$DateTag.csv"

$repos = Get-ChildItem -Directory $Root | Where-Object { Test-Path (Join-Path $_.FullName '.git') } | Sort-Object Name
$fileMetadataCache = @{}

function HasRemoteBranch($repoPath, $branch) {
  git -C $repoPath show-ref --verify --quiet "refs/remotes/origin/$branch" 2>$null
  return ($LASTEXITCODE -eq 0)
}

function GetCompareBase($repoPath, $left, $right) {
  $bases = @(git -C $repoPath merge-base $left $right 2>$null | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
  if ($LASTEXITCODE -ne 0 -or $bases.Count -eq 0) {
    return $null
  }

  return $bases[0].Trim()
}

function GetDirectionalContentDifferences($repoPath, $left, $right) {
  if ($CompareMode -eq 'merge_base') {
    $base = GetCompareBase $repoPath $left $right
    if ([string]::IsNullOrWhiteSpace($base)) {
      return @{
        ok = $false
        items = @()
      }
    }

    $raw = git -C $repoPath diff --name-status $base $right 2>$null
  } else {
    $raw = git -C $repoPath diff --name-status $left $right 2>$null
  }

  if ($LASTEXITCODE -ne 0) {
    return @{
      ok = $false
      items = @()
    }
  }

  $rows = New-Object System.Collections.Generic.List[object]

  foreach ($line in $raw) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }

    $parts = $line -split "`t"
    if ($parts.Count -lt 2) { continue }

    $status = $parts[0].Trim()
    $statusCode = ($status -replace '[0-9]+$','')
    $filePath = $parts[$parts.Count - 1].Trim()
    if ([string]::IsNullOrWhiteSpace($filePath)) { continue }

    $differenceType = switch ($statusCode) {
      'A' { 'right_only' }
      'D' { 'deleted_in_right' }
      'M' { 'different_content' }
      'R' { 'renamed_in_right' }
      'C' { 'copied_in_right' }
      'T' { 'different_content' }
      'U' { 'different_content' }
      'X' { 'different_content' }
      default { $null }
    }

    if (-not $differenceType) { continue }

    $rows.Add([pscustomobject]@{
      file_path = $filePath
      raw_change_type = $status
      difference_type = $differenceType
    }) | Out-Null
  }

  return @{
    ok = $true
    items = $rows.ToArray()
  }
}

function GetDirectionalFileCountByContent($repoPath, $left, $right) {
  $result = GetDirectionalContentDifferences $repoPath $left $right
  if (-not $result['ok']) { return 'N/A' }

  $rows = @($result['items'])
  if ($rows.Count -eq 0) { return 0 }

  $uniqueFiles = @($rows | Select-Object -ExpandProperty file_path -Unique)
  return $uniqueFiles.Count
}

function GetGitLogMetadata($repoPath, $argsList) {
  $output = @(git -C $repoPath log @argsList 2>$null)
  if ($LASTEXITCODE -ne 0 -or $output.Count -eq 0) {
    return @{
      commit = ''
      created_at = ''
      author = ''
      author_email = ''
      message = ''
    }
  }

  $line = ($output | Select-Object -First 1).Trim()
  if ([string]::IsNullOrWhiteSpace($line)) {
    return @{
      commit = ''
      created_at = ''
      author = ''
      author_email = ''
      message = ''
    }
  }

  $parts = $line -split '\|', 5
  return @{
    commit = if ($parts.Count -ge 1) { $parts[0] } else { '' }
    created_at = if ($parts.Count -ge 2) { $parts[1] } else { '' }
    author = if ($parts.Count -ge 3) { $parts[2] } else { '' }
    author_email = if ($parts.Count -ge 4) { $parts[3] } else { '' }
    message = if ($parts.Count -ge 5) { $parts[4] } else { '' }
  }
}

function GetFileMetadata($repoPath, $branch, $filePath) {
  $cacheKey = "$repoPath|$branch|$filePath"
  if ($fileMetadataCache.ContainsKey($cacheKey)) {
    return $fileMetadataCache[$cacheKey]
  }

  $treeMatch = @(git -C $repoPath ls-tree -r --name-only $branch -- $filePath 2>$null)
  $existsOnBranch = ($LASTEXITCODE -eq 0 -and $treeMatch.Count -gt 0)

  if (-not $existsOnBranch) {
    $result = @{
      exists_on_right_branch = $false
      created_commit = ''
      created_at = ''
      created_author = ''
      created_author_email = ''
      created_message = ''
      last_change_commit = ''
      last_change_at = ''
      last_change_author = ''
      last_change_author_email = ''
      last_change_message = ''
    }
    $fileMetadataCache[$cacheKey] = $result
    return $result
  }

  $created = GetGitLogMetadata $repoPath @('--diff-filter=A', '--follow', '-n', '1', '--format=%H|%ad|%an|%ae|%s', $branch, '--', $filePath)
  $lastChanged = GetGitLogMetadata $repoPath @('-n', '1', '--format=%H|%ad|%an|%ae|%s', $branch, '--', $filePath)

  $result = @{
    exists_on_right_branch = $true
    created_commit = $created['commit']
    created_at = $created['created_at']
    created_author = $created['author']
    created_author_email = $created['author_email']
    created_message = $created['message']
    last_change_commit = $lastChanged['commit']
    last_change_at = $lastChanged['created_at']
    last_change_author = $lastChanged['author']
    last_change_author_email = $lastChanged['author_email']
    last_change_message = $lastChanged['message']
  }

  $fileMetadataCache[$cacheKey] = $result
  return $result
}

$defs = @(
  @{ name = 'prod_not_in_master'; left = 'origin/master'; right = 'origin/production' },
  @{ name = 'prod_not_in_test'; left = 'origin/test'; right = 'origin/production' },
  @{ name = 'test_not_in_master'; left = 'origin/master'; right = 'origin/test' },
  @{ name = 'test_not_in_prod'; left = 'origin/production'; right = 'origin/test' },
  @{ name = 'master_not_in_test'; left = 'origin/test'; right = 'origin/master' },
  @{ name = 'master_not_in_prod'; left = 'origin/production'; right = 'origin/master' }
)

$fileCountRows = @()
$detailRows = New-Object System.Collections.Generic.List[object]
$totalRows = New-Object System.Collections.Generic.List[object]

foreach ($r in $repos) {
  $repo = $r.Name
  $path = $r.FullName
  $hasMaster = HasRemoteBranch $path 'master'
  $hasTest = HasRemoteBranch $path 'test'
  $hasProd = HasRemoteBranch $path 'production'

  $fm_not_t = 'N/A'
  $ft_not_m = 'N/A'
  $fp_not_t = 'N/A'
  $ft_not_p = 'N/A'
  $fp_not_m = 'N/A'
  $fm_not_p = 'N/A'

  if ($hasMaster -and $hasTest) {
    $fm_not_t = GetDirectionalFileCountByContent $path 'origin/test' 'origin/master'
    $ft_not_m = GetDirectionalFileCountByContent $path 'origin/master' 'origin/test'
  }
  if ($hasProd -and $hasTest) {
    $fp_not_t = GetDirectionalFileCountByContent $path 'origin/test' 'origin/production'
    $ft_not_p = GetDirectionalFileCountByContent $path 'origin/production' 'origin/test'
  }
  if ($hasProd -and $hasMaster) {
    $fp_not_m = GetDirectionalFileCountByContent $path 'origin/master' 'origin/production'
    $fm_not_p = GetDirectionalFileCountByContent $path 'origin/production' 'origin/master'
  }

  $fileCountRows += [pscustomobject]@{
    repo = $repo
    has_master = $hasMaster
    has_test = $hasTest
    has_production = $hasProd
    master_files_not_in_test_by_content = $fm_not_t
    test_files_not_in_master_by_content = $ft_not_m
    prod_files_not_in_test_by_content = $fp_not_t
    test_files_not_in_prod_by_content = $ft_not_p
    prod_files_not_in_master_by_content = $fp_not_m
    master_files_not_in_prod_by_content = $fm_not_p
  }

  foreach ($d in $defs) {
    $left = $d.left
    $right = $d.right

    git -C $path show-ref --verify --quiet ("refs/remotes/" + $left) 2>$null
    $hasLeft = ($LASTEXITCODE -eq 0)
    git -C $path show-ref --verify --quiet ("refs/remotes/" + $right) 2>$null
    $hasRight = ($LASTEXITCODE -eq 0)

    if (-not ($hasLeft -and $hasRight)) {
      $totalRows.Add([pscustomobject]@{
        repo = $repo
        discrepancy = $d.name
        left_branch = $left
        right_branch = $right
        total_file_rows = 'N/A'
        unique_files_affected = 'N/A'
        right_only_files = 'N/A'
        deleted_in_right_files = 'N/A'
        renamed_in_right_files = 'N/A'
        copied_in_right_files = 'N/A'
        different_content_files = 'N/A'
        status = 'missing_branch'
      }) | Out-Null
      continue
    }

    $result = GetDirectionalContentDifferences $path $left $right
    if (-not $result['ok']) {
      $totalRows.Add([pscustomobject]@{
        repo = $repo
        discrepancy = $d.name
        left_branch = $left
        right_branch = $right
        total_file_rows = 'N/A'
        unique_files_affected = 'N/A'
        right_only_files = 'N/A'
        deleted_in_right_files = 'N/A'
        renamed_in_right_files = 'N/A'
        copied_in_right_files = 'N/A'
        different_content_files = 'N/A'
        status = 'error'
      }) | Out-Null
      continue
    }

    $rows = @($result['items'])
    $rightOnlyCount = @($rows | Where-Object { $_.difference_type -eq 'right_only' }).Count
    $deletedInRightCount = @($rows | Where-Object { $_.difference_type -eq 'deleted_in_right' }).Count
    $renamedInRightCount = @($rows | Where-Object { $_.difference_type -eq 'renamed_in_right' }).Count
    $copiedInRightCount = @($rows | Where-Object { $_.difference_type -eq 'copied_in_right' }).Count
    $differentContentCount = @($rows | Where-Object { $_.difference_type -eq 'different_content' }).Count
    $uniqueFiles = @($rows | Select-Object -ExpandProperty file_path -Unique)

    foreach ($row in $rows) {
      $fileMeta = GetFileMetadata $path $right $row.file_path
      $detailRows.Add([pscustomobject]@{
        repo = $repo
        discrepancy = $d.name
        left_branch = $left
        right_branch = $right
        compare_mode = $CompareMode
        file_path = $row.file_path
        raw_change_type = $row.raw_change_type
        difference_type = $row.difference_type
        exists_on_right_branch = $fileMeta['exists_on_right_branch']
        created_commit = $fileMeta['created_commit']
        created_at = $fileMeta['created_at']
        created_author = $fileMeta['created_author']
        created_author_email = $fileMeta['created_author_email']
        created_message = $fileMeta['created_message']
        last_change_commit = $fileMeta['last_change_commit']
        last_change_at = $fileMeta['last_change_at']
        last_change_author = $fileMeta['last_change_author']
        last_change_author_email = $fileMeta['last_change_author_email']
        last_change_message = $fileMeta['last_change_message']
        problem_statement = if ($CompareMode -eq 'merge_base') {
          "File differs between merge-base($left, $right) and $right, matching GitLab compare semantics."
        } else {
          "File differs between branch tips $left and $right."
        }
      }) | Out-Null
    }

    $totalRows.Add([pscustomobject]@{
      repo = $repo
      discrepancy = $d.name
      left_branch = $left
      right_branch = $right
      compare_mode = $CompareMode
      total_file_rows = $rows.Count
      unique_files_affected = $uniqueFiles.Count
      right_only_files = $rightOnlyCount
      deleted_in_right_files = $deletedInRightCount
      renamed_in_right_files = $renamedInRightCount
      copied_in_right_files = $copiedInRightCount
      different_content_files = $differentContentCount
      status = 'ok'
    }) | Out-Null
  }
}

Write-Host "COMPARE_MODE=$CompareMode"
$fileCountRows | Sort-Object repo | Export-Csv -Path $outFileCounts -NoTypeInformation -Encoding UTF8
$detailRows    | Sort-Object repo, discrepancy, file_path | Export-Csv -Path $outDetail -NoTypeInformation -Encoding UTF8
$totalRows     | Sort-Object repo, discrepancy | Export-Csv -Path $outTotals -NoTypeInformation -Encoding UTF8

Write-Host "FILE_COUNTS=$outFileCounts"
Write-Host "DETAIL=$outDetail"
Write-Host "TOTALS=$outTotals"
