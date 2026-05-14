param(
  [string]$Root = 'c:\repos\fastossb\ndl_core',
  [string]$DateTag = (Get-Date -Format 'yyyy-MM-dd'),
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\\..\\outputs")
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

& (Join-Path $scriptDir 'sync_remote_branches.ps1') -Root $Root -DateTag $DateTag -OutputDir $OutputDir
& (Join-Path $scriptDir 'report_branch_discrepancies_by_commit.ps1') -Root $Root -DateTag $DateTag -OutputDir $OutputDir
