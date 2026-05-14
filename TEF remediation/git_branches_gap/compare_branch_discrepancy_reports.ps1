param(
  [string]$DateOld = '2026-03-02',
  [string]$DateNew = '2026-03-03',
  [string]$InputDir = (Join-Path $PSScriptRoot "..\\..\\outputs"),
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\\..\\outputs")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $OutputDir)) {
  New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$oldFile = Join-Path $InputDir "branch_discrepancy_file_commit_lines_prod_master_test_no_merges_$DateOld.csv"
$newFile = Join-Path $InputDir "branch_discrepancy_file_commit_lines_prod_master_test_no_merges_$DateNew.csv"

if(-not (Test-Path $oldFile)){ throw "Missing old report file: $oldFile" }
if(-not (Test-Path $newFile)){ throw "Missing new report file: $newFile" }

$rOld = Import-Csv $oldFile
$rNew = Import-Csv $newFile

$keysOld = @{}
foreach($r in $rOld){
  $k = "$($r.repo)|$($r.discrepancy)|$($r.commit)|$($r.file_path)"
  $keysOld[$k] = $r
}

$keysNew = @{}
foreach($r in $rNew){
  $k = "$($r.repo)|$($r.discrepancy)|$($r.commit)|$($r.file_path)"
  $keysNew[$k] = $r
}

$onlyOld = New-Object System.Collections.Generic.List[object]
foreach($k in $keysOld.Keys){
  if(-not $keysNew.ContainsKey($k)){
    $onlyOld.Add($keysOld[$k]) | Out-Null
  }
}

$onlyNew = New-Object System.Collections.Generic.List[object]
foreach($k in $keysNew.Keys){
  if(-not $keysOld.ContainsKey($k)){
    $onlyNew.Add($keysNew[$k]) | Out-Null
  }
}

$gOld = $rOld | Group-Object repo,discrepancy | ForEach-Object {
  $parts = $_.Name -split ', '
  [pscustomobject]@{ repo = $parts[0]; discrepancy = $parts[1]; count_old = $_.Count }
}

$gNew = $rNew | Group-Object repo,discrepancy | ForEach-Object {
  $parts = $_.Name -split ', '
  [pscustomobject]@{ repo = $parts[0]; discrepancy = $parts[1]; count_new = $_.Count }
}

$pairMap = @{}
foreach($x in $gOld){
  $pairMap["$($x.repo)|$($x.discrepancy)"] = [pscustomobject]@{
    repo = $x.repo
    discrepancy = $x.discrepancy
    count_old = [int]$x.count_old
    count_new = 0
    delta = 0
  }
}
foreach($x in $gNew){
  $k = "$($x.repo)|$($x.discrepancy)"
  if($pairMap.ContainsKey($k)){
    $pairMap[$k].count_new = [int]$x.count_new
  } else {
    $pairMap[$k] = [pscustomobject]@{
      repo = $x.repo
      discrepancy = $x.discrepancy
      count_old = 0
      count_new = [int]$x.count_new
      delta = 0
    }
  }
}

$pairChanges = New-Object System.Collections.Generic.List[object]
foreach($v in $pairMap.Values){
  $v.delta = $v.count_new - $v.count_old
  if($v.delta -ne 0){
    $pairChanges.Add($v) | Out-Null
  }
}

$summary = [pscustomobject]@{
  date_old = $DateOld
  date_new = $DateNew
  rows_old = $rOld.Count
  rows_new = $rNew.Count
  delta_rows = ($rNew.Count - $rOld.Count)
  only_in_old = $onlyOld.Count
  only_in_new = $onlyNew.Count
  changed_repo_discrepancy_pairs = $pairChanges.Count
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$summaryFile = Join-Path $OutputDir "discrepancy_report_diff_summary_${DateOld}_vs_${DateNew}_$stamp.csv"
$pairFile = Join-Path $OutputDir "discrepancy_report_diff_pairs_${DateOld}_vs_${DateNew}_$stamp.csv"
$onlyOldFile = Join-Path $OutputDir "discrepancy_report_only_in_${DateOld}_$stamp.csv"
$onlyNewFile = Join-Path $OutputDir "discrepancy_report_only_in_${DateNew}_$stamp.csv"

@($summary) | Export-Csv -Path $summaryFile -NoTypeInformation -Encoding UTF8
$pairChanges | Sort-Object repo,discrepancy | Export-Csv -Path $pairFile -NoTypeInformation -Encoding UTF8
$onlyOld | Sort-Object repo,discrepancy,commit,file_path | Export-Csv -Path $onlyOldFile -NoTypeInformation -Encoding UTF8
$onlyNew | Sort-Object repo,discrepancy,commit,file_path | Export-Csv -Path $onlyNewFile -NoTypeInformation -Encoding UTF8

Write-Host "SUMMARY=$summaryFile"
Write-Host "PAIR_CHANGES=$pairFile"
Write-Host "ONLY_OLD=$onlyOldFile"
Write-Host "ONLY_NEW=$onlyNewFile"
Write-Host "rows_old=$($summary.rows_old) rows_new=$($summary.rows_new) delta_rows=$($summary.delta_rows)"
Write-Host "only_in_old=$($summary.only_in_old) only_in_new=$($summary.only_in_new) changed_pairs=$($summary.changed_repo_discrepancy_pairs)"
