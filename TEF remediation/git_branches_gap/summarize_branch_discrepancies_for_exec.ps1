param(
  [string]$DateTag = (Get-Date -Format 'yyyy-MM-dd'),
  [string]$InputDir = (Join-Path $PSScriptRoot "..\\..\\outputs"),
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\\..\\outputs")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $OutputDir)) {
  New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$totalsFile = Join-Path $InputDir "branch_discrepancy_file_totals_prod_master_test_no_merges_$DateTag.csv"
$detailFile = Join-Path $InputDir "branch_discrepancy_file_commit_lines_prod_master_test_no_merges_$DateTag.csv"
$countsFile = Join-Path $InputDir "branch_discrepancy_counts_prod_master_test_no_merges_$DateTag.csv"

if(-not (Test-Path $totalsFile)){ throw "Missing totals file: $totalsFile" }
if(-not (Test-Path $detailFile)){ throw "Missing detail file: $detailFile" }
if(-not (Test-Path $countsFile)){ throw "Missing counts file: $countsFile" }

$t = Import-Csv $totalsFile
$d = Import-Csv $detailFile
$c = Import-Csv $countsFile

$reposAll = $t.repo | Sort-Object -Unique
$tOk = $t | Where-Object { $_.status -eq 'ok' }

$repoStatus = $tOk | Group-Object repo | ForEach-Object {
  $nonzero = @($_.Group | Where-Object { [int]$_.unique_files_affected -gt 0 }).Count
  [pscustomobject]@{
    repo = $_.Name
    nonzero_pairs = $nonzero
    aligned = ($nonzero -eq 0)
  }
}

function SumInt($rows, $col){
  ($rows | ForEach-Object { if($_.$col -and $_.$col -ne 'N/A'){ [int]$_.$col } else { 0 } } | Measure-Object -Sum).Sum
}

$dates = @($d.created_at | ForEach-Object { try { [datetimeoffset]$_ } catch { $null } } | Where-Object { $_ -ne $null })
$minDate = if($dates.Count -gt 0){ ($dates | Sort-Object | Select-Object -First 1).ToString('yyyy-MM-dd HH:mm:ss zzz') } else { '' }
$maxDate = if($dates.Count -gt 0){ ($dates | Sort-Object | Select-Object -Last 1).ToString('yyyy-MM-dd HH:mm:ss zzz') } else { '' }

$summary = [pscustomobject]@{
  date_tag = $DateTag
  total_repos = $reposAll.Count
  total_repo_discrepancy_pairs = $t.Count
  pairs_ok = ($t | Where-Object { $_.status -eq 'ok' }).Count
  pairs_with_missing_branch = ($t | Where-Object { $_.status -ne 'ok' }).Count
  pairs_with_nonzero_files = ($tOk | Where-Object { [int]$_.unique_files_affected -gt 0 }).Count
  repos_with_complete_branches = ($tOk.repo | Sort-Object -Unique).Count
  repos_fully_aligned = ($repoStatus | Where-Object { $_.aligned }).Count
  repos_with_any_discrepancy = ($repoStatus | Where-Object { -not $_.aligned }).Count
  total_detail_rows = $d.Count
  total_unique_files_across_detail = ($d.file_path | Sort-Object -Unique).Count
  total_unique_commits_across_detail = ($d.commit | Sort-Object -Unique).Count
  min_discrepancy_commit_date = $minDate
  max_discrepancy_commit_date = $maxDate
  sum_unique_files_prod_not_in_test = SumInt ($tOk | Where-Object { $_.discrepancy -eq 'prod_not_in_test' }) 'unique_files_affected'
  sum_unique_files_prod_not_in_master = SumInt ($tOk | Where-Object { $_.discrepancy -eq 'prod_not_in_master' }) 'unique_files_affected'
  sum_unique_files_test_not_in_prod = SumInt ($tOk | Where-Object { $_.discrepancy -eq 'test_not_in_prod' }) 'unique_files_affected'
  sum_unique_files_master_not_in_prod = SumInt ($tOk | Where-Object { $_.discrepancy -eq 'master_not_in_prod' }) 'unique_files_affected'
  sum_commits_prod_not_in_master = SumInt $c 'prod_not_in_master_commits_no_merges'
  sum_commits_prod_not_in_test = SumInt $c 'prod_not_in_test_commits_no_merges'
  sum_commits_test_not_in_master = SumInt $c 'test_not_in_master_commits_no_merges'
  sum_commits_test_not_in_prod = SumInt $c 'test_not_in_prod_commits_no_merges'
  sum_commits_master_not_in_test = SumInt $c 'master_not_in_test_commits_no_merges'
  sum_commits_master_not_in_prod = SumInt $c 'master_not_in_prod_commits_no_merges'
}

$topReposByFiles = $tOk | Group-Object repo | ForEach-Object {
  [pscustomobject]@{
    repo = $_.Name
    total_unique_files = SumInt $_.Group 'unique_files_affected'
    nonzero_pairs = @($_.Group | Where-Object { [int]$_.unique_files_affected -gt 0 }).Count
  }
} | Sort-Object total_unique_files -Descending

$topByDiscrepancy = $tOk | Group-Object discrepancy | ForEach-Object {
  [pscustomobject]@{
    discrepancy = $_.Name
    repos_with_nonzero = ($_.Group | Where-Object { [int]$_.unique_files_affected -gt 0 } | Select-Object -ExpandProperty repo -Unique).Count
    sum_unique_files = SumInt $_.Group 'unique_files_affected'
    sum_unique_commits = SumInt $_.Group 'unique_commits'
  }
} | Sort-Object discrepancy

$contributors = $d | Group-Object author | ForEach-Object {
  [pscustomobject]@{
    author = $_.Name
    rows = $_.Count
    unique_commits = @($_.Group.commit | Sort-Object -Unique).Count
    unique_files = @($_.Group.file_path | Sort-Object -Unique).Count
  }
} | Sort-Object rows -Descending

$normalizedContributors = $d | ForEach-Object {
  $a = $_.author -replace ' \(External\)$',''
  [pscustomobject]@{ author=$a; commit=$_.commit; file=$_.file_path }
} | Group-Object author | ForEach-Object {
  [pscustomobject]@{
    author = $_.Name
    rows = $_.Count
    unique_commits = @($_.Group.commit | Sort-Object -Unique).Count
    unique_files = @($_.Group.file | Sort-Object -Unique).Count
  }
} | Sort-Object rows -Descending

$signals = @('cherry-pick','Merge branch','revert','patch:','minor:','major:')
$signalRows = foreach($s in $signals){
  [pscustomobject]@{
    signal = $s
    row_count = ($d | Where-Object { $_.message -match [regex]::Escape($s) }).Count
  }
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$summaryOut = Join-Path $OutputDir "executive_summary_stats_$DateTag`_$stamp.csv"
$reposOut = Join-Path $OutputDir "executive_top_repos_by_files_$DateTag`_$stamp.csv"
$discOut = Join-Path $OutputDir "executive_by_discrepancy_$DateTag`_$stamp.csv"
$authOut = Join-Path $OutputDir "executive_top_contributors_raw_$DateTag`_$stamp.csv"
$authNormOut = Join-Path $OutputDir "executive_top_contributors_normalized_$DateTag`_$stamp.csv"
$signalsOut = Join-Path $OutputDir "executive_message_signals_$DateTag`_$stamp.csv"
$repoStatusOut = Join-Path $OutputDir "executive_repo_alignment_status_$DateTag`_$stamp.csv"

@($summary) | Export-Csv -Path $summaryOut -NoTypeInformation -Encoding UTF8
$topReposByFiles | Export-Csv -Path $reposOut -NoTypeInformation -Encoding UTF8
$topByDiscrepancy | Export-Csv -Path $discOut -NoTypeInformation -Encoding UTF8
$contributors | Export-Csv -Path $authOut -NoTypeInformation -Encoding UTF8
$normalizedContributors | Export-Csv -Path $authNormOut -NoTypeInformation -Encoding UTF8
$signalRows | Export-Csv -Path $signalsOut -NoTypeInformation -Encoding UTF8
$repoStatus | Export-Csv -Path $repoStatusOut -NoTypeInformation -Encoding UTF8

Write-Host "SUMMARY=$summaryOut"
Write-Host "TOP_REPOS=$reposOut"
Write-Host "BY_DISCREPANCY=$discOut"
Write-Host "TOP_CONTRIBUTORS_RAW=$authOut"
Write-Host "TOP_CONTRIBUTORS_NORMALIZED=$authNormOut"
Write-Host "MESSAGE_SIGNALS=$signalsOut"
Write-Host "REPO_ALIGNMENT=$repoStatusOut"
