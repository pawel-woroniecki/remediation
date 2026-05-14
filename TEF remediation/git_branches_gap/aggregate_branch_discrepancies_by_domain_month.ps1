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

$inFile = Join-Path $InputDir "discrepancy_domain_month_type_$DateTag.csv"
if(-not (Test-Path $inFile)){
  throw "Missing input file: $inFile"
}

$d = Import-Csv $inFile

$agg = $d | Group-Object domain,month_year | ForEach-Object {
  $parts = $_.Name -split ', '
  [pscustomobject]@{
    domain = $parts[0]
    month_year = $parts[1]
    detail_rows = ($_.Group | ForEach-Object { [int]$_.detail_rows } | Measure-Object -Sum).Sum
    unique_commits = ($_.Group | ForEach-Object { [int]$_.unique_commits } | Measure-Object -Sum).Sum
    unique_files = ($_.Group | ForEach-Object { [int]$_.unique_files } | Measure-Object -Sum).Sum
  }
} | Sort-Object domain,month_year

$outFile = Join-Path $OutputDir "discrepancy_domain_month_$DateTag.csv"
$agg | Export-Csv -Path $outFile -NoTypeInformation -Encoding UTF8

Write-Host "INPUT=$inFile"
Write-Host "OUTPUT=$outFile"
Write-Host "ROWS_IN=$($d.Count)"
Write-Host "ROWS_OUT=$($agg.Count)"
