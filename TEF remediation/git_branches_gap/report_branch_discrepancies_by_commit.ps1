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

$outCommitCounts = Join-Path $OutputDir "branch_discrepancy_counts_prod_master_test_no_merges_$DateTag.csv"
$outFileCounts   = Join-Path $OutputDir "branch_discrepancy_file_counts_prod_master_test_no_merges_$DateTag.csv"
$outDetail       = Join-Path $OutputDir "branch_discrepancy_file_commit_lines_prod_master_test_no_merges_$DateTag.csv"
$outTotals       = Join-Path $OutputDir "branch_discrepancy_file_totals_prod_master_test_no_merges_$DateTag.csv"

$repos = Get-ChildItem -Directory $Root | Where-Object { Test-Path (Join-Path $_.FullName '.git') } | Sort-Object Name

function HasRemoteBranch($repoPath,$branch){
  git -C $repoPath show-ref --verify --quiet "refs/remotes/origin/$branch" 2>$null
  return ($LASTEXITCODE -eq 0)
}

function GetPairCountsNoMerges($repoPath,$left,$right){
  $raw = git -C $repoPath rev-list --no-merges --left-right --cherry-pick --count "$left...$right" 2>$null
  if($LASTEXITCODE -ne 0 -or -not $raw){ return $null }
  $p = ($raw -split '\s+') | Where-Object { $_ -ne '' }
  if($p.Count -lt 2){ return $null }
  return [pscustomobject]@{ left=[int]$p[0]; right=[int]$p[1] }
}

function GetUniqueFileCountNoMerges($repoPath,$left,$right){
  $files = git -C $repoPath log --no-merges --right-only --cherry-pick --name-only --pretty=format: "$left...$right" 2>$null
  if($LASTEXITCODE -ne 0){ return 'N/A' }
  if(-not $files){ return 0 }
  $u = @($files | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_.Trim() } | Sort-Object -Unique)
  if($u.Count -eq 0){ return 0 }
  return $u.Count
}

$defs = @(
  @{ name='prod_not_in_master'; left='origin/master'; right='origin/production'; problem='File changed in production patch-unique non-merge commits not present in master.' },
  @{ name='prod_not_in_test'; left='origin/test'; right='origin/production'; problem='File changed in production patch-unique non-merge commits not present in test.' },
  @{ name='test_not_in_master'; left='origin/master'; right='origin/test'; problem='File changed in test patch-unique non-merge commits not present in master.' },
  @{ name='test_not_in_prod'; left='origin/production'; right='origin/test'; problem='File changed in test patch-unique non-merge commits not present in production.' },
  @{ name='master_not_in_test'; left='origin/test'; right='origin/master'; problem='File changed in master patch-unique non-merge commits not present in test.' },
  @{ name='master_not_in_prod'; left='origin/production'; right='origin/master'; problem='File changed in master patch-unique non-merge commits not present in production.' }
)

$commitCountRows = @()
$fileCountRows = @()
$detailRows = New-Object System.Collections.Generic.List[object]
$totalRows = New-Object System.Collections.Generic.List[object]

foreach($r in $repos){
  $repo = $r.Name
  $path = $r.FullName
  $hasMaster = HasRemoteBranch $path 'master'
  $hasTest = HasRemoteBranch $path 'test'
  $hasProd = HasRemoteBranch $path 'production'

  $m_not_t='N/A'; $t_not_m='N/A'; $p_not_t='N/A'; $t_not_p='N/A'; $p_not_m='N/A'; $m_not_p='N/A'
  if($hasMaster -and $hasTest){
    $c = GetPairCountsNoMerges $path 'origin/master' 'origin/test'
    if($c){ $m_not_t=$c.left; $t_not_m=$c.right }
  }
  if($hasProd -and $hasTest){
    $c = GetPairCountsNoMerges $path 'origin/production' 'origin/test'
    if($c){ $p_not_t=$c.left; $t_not_p=$c.right }
  }
  if($hasProd -and $hasMaster){
    $c = GetPairCountsNoMerges $path 'origin/production' 'origin/master'
    if($c){ $p_not_m=$c.left; $m_not_p=$c.right }
  }

  $commitCountRows += [pscustomobject]@{
    repo=$repo; has_master=$hasMaster; has_test=$hasTest; has_production=$hasProd;
    master_not_in_test_commits_no_merges=$m_not_t;
    test_not_in_master_commits_no_merges=$t_not_m;
    prod_not_in_test_commits_no_merges=$p_not_t;
    test_not_in_prod_commits_no_merges=$t_not_p;
    prod_not_in_master_commits_no_merges=$p_not_m;
    master_not_in_prod_commits_no_merges=$m_not_p
  }

  $fm_not_t='N/A'; $ft_not_m='N/A'; $fp_not_t='N/A'; $ft_not_p='N/A'; $fp_not_m='N/A'; $fm_not_p='N/A'
  if($hasMaster -and $hasTest){
    $fm_not_t = GetUniqueFileCountNoMerges $path 'origin/test' 'origin/master'
    $ft_not_m = GetUniqueFileCountNoMerges $path 'origin/master' 'origin/test'
  }
  if($hasProd -and $hasTest){
    $fp_not_t = GetUniqueFileCountNoMerges $path 'origin/test' 'origin/production'
    $ft_not_p = GetUniqueFileCountNoMerges $path 'origin/production' 'origin/test'
  }
  if($hasProd -and $hasMaster){
    $fp_not_m = GetUniqueFileCountNoMerges $path 'origin/master' 'origin/production'
    $fm_not_p = GetUniqueFileCountNoMerges $path 'origin/production' 'origin/master'
  }

  $fileCountRows += [pscustomobject]@{
    repo=$repo; has_master=$hasMaster; has_test=$hasTest; has_production=$hasProd;
    master_files_not_in_test_no_merges=$fm_not_t;
    test_files_not_in_master_no_merges=$ft_not_m;
    prod_files_not_in_test_no_merges=$fp_not_t;
    test_files_not_in_prod_no_merges=$ft_not_p;
    prod_files_not_in_master_no_merges=$fp_not_m;
    master_files_not_in_prod_no_merges=$fm_not_p
  }

  foreach($d in $defs){
    $left=$d.left; $right=$d.right
    git -C $path show-ref --verify --quiet ("refs/remotes/" + $left) 2>$null; $hasLeft=($LASTEXITCODE -eq 0)
    git -C $path show-ref --verify --quiet ("refs/remotes/" + $right) 2>$null; $hasRight=($LASTEXITCODE -eq 0)

    if(-not ($hasLeft -and $hasRight)){
      $totalRows.Add([pscustomobject]@{repo=$repo; discrepancy=$d.name; left_branch=$left; right_branch=$right; total_file_lines='N/A'; unique_files_affected='N/A'; unique_commits='N/A'; status='missing_branch'}) | Out-Null
      continue
    }

    $raw = git -C $path log --no-merges --right-only --cherry-pick --date=iso --name-only --pretty=format:'@@@%H|%ad|%an|%ae|%s' "$left...$right" 2>$null

    $currentHash=''; $currentDate=''; $currentAuthor=''; $currentAuthorEmail=''; $currentMsg=''
    $fileSet = New-Object 'System.Collections.Generic.HashSet[string]'
    $commitSet = New-Object 'System.Collections.Generic.HashSet[string]'
    $lineCount = 0

    foreach($line in $raw){
      if([string]::IsNullOrWhiteSpace($line)){ continue }
      if($line.StartsWith('@@@')){
        $meta = $line.Substring(3)
        $parts = $meta -split '\|',5
        if($parts.Count -ge 5){
          $currentHash=$parts[0]; $currentDate=$parts[1]; $currentAuthor=$parts[2]; $currentAuthorEmail=$parts[3]; $currentMsg=$parts[4]
          [void]$commitSet.Add($currentHash)
        }
        continue
      }
      if([string]::IsNullOrWhiteSpace($currentHash)){ continue }
      $file=$line.Trim()
      if([string]::IsNullOrWhiteSpace($file)){ continue }

      $lineCount++
      [void]$fileSet.Add($file)

      $detailRows.Add([pscustomobject]@{
        repo=$repo; discrepancy=$d.name; left_branch=$left; right_branch=$right;
        commit=$currentHash; created_at=$currentDate; author=$currentAuthor; author_email=$currentAuthorEmail; message=$currentMsg;
        file_path=$file; problem_statement=$d.problem
      }) | Out-Null
    }

    $totalRows.Add([pscustomobject]@{
      repo=$repo; discrepancy=$d.name; left_branch=$left; right_branch=$right;
      total_file_lines=$lineCount; unique_files_affected=$fileSet.Count; unique_commits=$commitSet.Count; status='ok'
    }) | Out-Null
  }
}

$commitCountRows | Sort-Object repo | Export-Csv -Path $outCommitCounts -NoTypeInformation -Encoding UTF8
$fileCountRows   | Sort-Object repo | Export-Csv -Path $outFileCounts -NoTypeInformation -Encoding UTF8
$detailRows      | Sort-Object repo,discrepancy,created_at,commit,file_path | Export-Csv -Path $outDetail -NoTypeInformation -Encoding UTF8
$totalRows       | Sort-Object repo,discrepancy | Export-Csv -Path $outTotals -NoTypeInformation -Encoding UTF8

Write-Host "COMMIT_COUNTS=$outCommitCounts"
Write-Host "FILE_COUNTS=$outFileCounts"
Write-Host "DETAIL=$outDetail"
Write-Host "TOTALS=$outTotals"
