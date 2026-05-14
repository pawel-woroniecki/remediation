param(
  [string]$Root = 'c:\repos\fastossb\ndl_core',
  [string]$DateTag = (Get-Date -Format 'yyyy-MM-dd'),
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\\..\\outputs"),
  [switch]$SkipRefresh,
  [ValidateSet('merge_base','direct')]
  [string]$CompareMode = 'merge_base'
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$refreshScript = Join-Path $scriptDir 'sync_remote_branches.ps1'
$reportScript = Join-Path $scriptDir 'report_branch_discrepancies_by_content_compat.ps1'
$steps = @(
  @{ Number = 1; Path = $refreshScript; Name = 'sync_remote_branches.ps1' },
  @{ Number = 2; Path = $reportScript; Name = 'report_branch_discrepancies_by_content_compat.ps1' }
)

Write-Host "[run_branch_discrepancy_workflow_by_content_compat] Starting wrapper"
Write-Host "[run_branch_discrepancy_workflow_by_content_compat] Root=$Root DateTag=$DateTag OutputDir=$OutputDir CompareMode=$CompareMode"
Write-Host "[run_branch_discrepancy_workflow_by_content_compat] We will execute $($steps.Count) scripts"
if ($SkipRefresh) {
  Write-Host "[run_branch_discrepancy_workflow_by_content_compat] Step 1/$($steps.Count): Skipping ${refreshScript}"
} else {
  Write-Host "[run_branch_discrepancy_workflow_by_content_compat] Step 1/$($steps.Count): Executing ${refreshScript}"
  & $refreshScript -Root $Root -DateTag $DateTag -OutputDir $OutputDir
}
Write-Host "[run_branch_discrepancy_workflow_by_content_compat] Step 2/$($steps.Count): Executing ${reportScript}"
& $reportScript -Root $Root -DateTag $DateTag -OutputDir $OutputDir -CompareMode $CompareMode
Write-Host "[run_branch_discrepancy_workflow_by_content_compat] Finished"
