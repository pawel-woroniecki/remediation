param(
  [string]$Root = 'c:\repos\fastossb\ndl_core',
  [string]$DateTag = (Get-Date -Format 'yyyy-MM-dd'),
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\\..\\outputs"),
  [ValidateSet('merge_base','direct')]
  [string]$CompareMode = 'merge_base'
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$contentScript = Join-Path $scriptDir 'report_branch_discrepancies_by_content.ps1'
$steps = @(
  @{ Number = 1; Path = $contentScript; Name = 'report_branch_discrepancies_by_content.ps1' }
)

Write-Host "[report_branch_discrepancies_by_content_compat] Starting wrapper"
Write-Host "[report_branch_discrepancies_by_content_compat] Root=$Root DateTag=$DateTag OutputDir=$OutputDir CompareMode=$CompareMode"
Write-Host "[report_branch_discrepancies_by_content_compat] We will execute $($steps.Count) script"
Write-Host "[report_branch_discrepancies_by_content_compat] Step 1/$($steps.Count): Executing ${contentScript}"
& $contentScript -Root $Root -DateTag $DateTag -OutputDir $OutputDir -CompareMode $CompareMode
Write-Host "[report_branch_discrepancies_by_content_compat] Finished"
